import unittest

import hashlib
import os
import os.path
import subprocess
import tempfile
import time

import fixture
import sheep


class ThreeNodesTwoCopiesTest(unittest.TestCase):
    _NR_NODES = 3
    _COPIES = 2
    _ports = []
    _disks = []

    @classmethod
    def setUpClass(clazz):
        for i in range(clazz._NR_NODES):
            t = fixture.CreateSheepdogDisk(1024 ** 3)
            p = i + 7000
            z = i + 1
            fixture.StartSheep(t[1], port=p, zone=z)
            clazz._ports.append(p)
            clazz._disks.append(t)
        time.sleep(2)

    @classmethod
    def tearDownClass(clazz):
        fixture.ShutdownCluster()
        time.sleep(2)
        for t in clazz._disks:
            fixture.DestroySheepdogDisk(t[0], t[1])

    def _assertUnique(self, function, iterable):
        filtered = filter(function, iterable)
        self.assertEqual(1, len(filtered))
        return filtered[0]

    def _assertUniqueName(self, name, iterable):
        return self._assertUnique(lambda x: x["name"] == name, iterable)

    def setUp(self):
        fixture.ForceFormatCluster(self.__class__._COPIES)

    def testReadObj(self):
        NB_OBJECT = 1 << 22
        NB_VDI = NB_OBJECT * 4
        assert NB_VDI % NB_OBJECT == 0

        self.assertTrue(fixture.CreateVDI("alpha", NB_VDI))

        alpha = self._assertUniqueName("alpha", fixture.ListVDI())
        self.assertEqual(NB_VDI, alpha["nb_size"])
        a_vid = alpha["vdi_id"]

        contentToWrite = os.urandom(NB_VDI)
        self.assertEqual(NB_VDI, len(contentToWrite))
        self.assertTrue(fixture.WriteVDI("alpha", contentToWrite))

        for p in self.__class__._ports:
            client = sheep.SheepdogClient(port=p)
            for i in range(NB_VDI / NB_OBJECT):
                oid = (a_vid << 32) | i
                response = client.read_obj(oid, 0, NB_OBJECT)
                contentRead = response.data
                self.assertEqual(NB_OBJECT, len(contentRead))

                s = NB_OBJECT * i
                e = NB_OBJECT * (i + 1)

                expected = hashlib.md5(contentToWrite[s:e]).digest()
                actual = hashlib.md5(contentRead).digest()
                self.assertEqual(expected, actual)

    def testReadObjOffset(self):
        NB_OBJECT = 1 << 22
        NB_SUBOBJECT = NB_OBJECT / 4
        assert NB_OBJECT % NB_SUBOBJECT == 0

        self.assertTrue(fixture.CreateVDI("alpha", NB_OBJECT))

        alpha = self._assertUniqueName("alpha", fixture.ListVDI())
        self.assertEqual(NB_OBJECT, alpha["nb_size"])
        a_vid = alpha["vdi_id"]
        oid = a_vid << 32

        contentToWrite = os.urandom(NB_OBJECT)
        self.assertEqual(NB_OBJECT, len(contentToWrite))
        self.assertTrue(fixture.WriteVDI("alpha", contentToWrite))

        for p in self.__class__._ports:
            client = sheep.SheepdogClient(port=p)
            for i in range(NB_OBJECT / NB_SUBOBJECT):
                s = NB_SUBOBJECT * i
                e = NB_SUBOBJECT * (i + 1)

                response = client.read_obj(oid, s, NB_SUBOBJECT)
                contentRead = response.data
                self.assertEqual(NB_SUBOBJECT, len(contentRead))

                expected = hashlib.md5(contentToWrite[s:e]).digest()
                actual = hashlib.md5(contentRead).digest()
                self.assertEqual(expected, actual)

    def testGetVDICopies(self):
        self.assertTrue(fixture.CreateVDI("alpha"))
        self.assertTrue(fixture.CreateVDI("bravo"))

        vdis = fixture.ListVDI()
        self.assertEqual(2, len(vdis))

        alpha = self._assertUniqueName("alpha", vdis)
        a_vid = alpha["vdi_id"]
        bravo = self._assertUniqueName("bravo", vdis)
        b_vid = bravo["vdi_id"]

        for p in self.__class__._ports:
            client = sheep.SheepdogClient(port=p)
            status = client.get_vdi_copies(1)
            self.assertEqual(2, len(status))

            a_state = self._assertUnique(lambda x: x.vid == a_vid, status)
            self.assertEqual(2, a_state.nr_copies)
            self.assertEqual(0, a_state.snapshot)
            self.assertEqual(0, a_state.deleted)
            self.assertEqual(0, a_state.copy_policy)
            self.assertEqual(22, a_state.block_size_shift)
            self.assertEqual(0, a_state.parent_vid)

            b_state = self._assertUnique(lambda x: x.vid == b_vid, status)
            self.assertEqual(2, b_state.nr_copies)
            self.assertEqual(0, b_state.snapshot)
            self.assertEqual(0, b_state.deleted)
            self.assertEqual(0, b_state.copy_policy)
            self.assertEqual(22, b_state.block_size_shift)
            self.assertEqual(0, b_state.parent_vid)

    def testGetVDICopiesDeleted(self):
        self.assertTrue(fixture.CreateVDI("alpha"))
        self.assertTrue(fixture.DeleteVDI("alpha"))
        self.assertEqual(0, len(fixture.ListVDI()))

        for p in self.__class__._ports:
            client = sheep.SheepdogClient(port=p)
            status = client.get_vdi_copies(1)
            a_state = self._assertUnique(None, status)
            self.assertEqual(1, a_state.deleted)

    def testGetVDICopiesSnapshot(self):
        self.assertTrue(fixture.CreateVDI("alpha"))
        self.assertTrue(fixture.SnapshotVDI("alpha", "alpha_1"))

        vdis = fixture.ListVDI()
        self.assertEqual(2, len(vdis))

        alpha = self._assertUnique(lambda x: not x["snapshot"], vdis)
        self.assertEqual("alpha", alpha["name"])
        a_vid = alpha["vdi_id"]

        snap = self._assertUnique(lambda x: x["snapshot"], vdis)
        self.assertEqual("alpha", snap["name"])
        self.assertEqual("alpha_1", snap["tag"])
        s_vid = snap["vdi_id"]

        for p in self.__class__._ports:
            client = sheep.SheepdogClient(port=p)
            status = client.get_vdi_copies(1)
            self.assertEqual(2, len(status))

            a_state = self._assertUnique(lambda x: x.vid == a_vid, status)
            self.assertEqual(2, a_state.nr_copies)
            self.assertEqual(0, a_state.snapshot)
            self.assertEqual(0, a_state.deleted)
            self.assertEqual(0, a_state.copy_policy)
            self.assertEqual(22, a_state.block_size_shift)
            self.assertEqual(s_vid, a_state.parent_vid)

            s_state = self._assertUnique(lambda x: x.vid == s_vid, status)
            self.assertEqual(2, s_state.nr_copies)
            self.assertEqual(1, s_state.snapshot)
            self.assertEqual(0, s_state.deleted)
            self.assertEqual(0, s_state.copy_policy)
            self.assertEqual(22, s_state.block_size_shift)
            self.assertEqual(0, s_state.parent_vid)

    def testReadVDIs(self):
        self.assertTrue(fixture.CreateVDI("alpha"))
        self.assertTrue(fixture.SnapshotVDI("alpha", "alpha_1"))

        vdis = fixture.ListVDI()
        self.assertEqual(2, len(vdis))

        alpha = self._assertUnique(lambda x: not x["snapshot"], vdis)
        self.assertEqual("alpha", alpha["name"])
        a_vid = alpha["vdi_id"]

        snap = self._assertUnique(lambda x: x["snapshot"], vdis)
        self.assertEqual("alpha", snap["name"])
        self.assertEqual("alpha_1", snap["tag"])
        s_vid = snap["vdi_id"]

        for p in self.__class__._ports:
            client = sheep.SheepdogClient(port=p)
            inuse = client.get_vids()
            self.assertEqual(2, len(inuse))
            self.assertTrue(a_vid in inuse)
            self.assertTrue(s_vid in inuse)

    def testReadDelVDIs(self):
        self.assertTrue(fixture.CreateVDI("alpha"))
        alpha = self._assertUniqueName("alpha", fixture.ListVDI())
        a_vid = alpha["vdi_id"]

        self.assertTrue(fixture.DeleteVDI("alpha"))
        self.assertEqual(0, len(fixture.ListVDI()))

        for p in self.__class__._ports:
            client = sheep.SheepdogClient(port=p)
            deleted = client.get_del_vids()
            self.assertEqual(1, len(deleted))
            self.assertTrue(a_vid in deleted)

    def testGetVDIsFrom(self):
        self.assertTrue(fixture.CreateVDI("alpha"))
        self.assertTrue(fixture.CreateVDI("bravo"))
        vdis = fixture.ListVDI()
        self.assertEqual(2, len(vdis))

        alpha = self._assertUniqueName("alpha", vdis)
        a_vid = alpha["vdi_id"]
        bravo = self._assertUniqueName("bravo", vdis)
        b_vid = bravo["vdi_id"]

        self.assertTrue(fixture.DeleteVDI("bravo"))
        self.assertEqual(1, len(fixture.ListVDI()))

        for p in self.__class__._ports:
            client = sheep.SheepdogClient(port=p)

            # before
            status = client.get_vdi_copies(1)
            self.assertEqual(2, len(status))
            a_state = self._assertUnique(lambda x: x.vid == a_vid, status)
            b_state = self._assertUnique(lambda x: x.vid == b_vid, status)
            self.assertEqual(1, b_state.deleted)

            # after
            deleted = client.get_del_vids()
            self.assertEqual(1, len(deleted))
            self.assertTrue(a_vid not in deleted)
            self.assertTrue(b_vid in deleted)
            inuse = client.get_vids()
            self.assertTrue(a_vid in inuse)
            a_inode = client.get_inode(a_vid)

            self.assertEqual(a_state.nr_copies, a_inode.nr_copies)
            self.assertEqual(bool(a_state.snapshot), bool(a_inode.snap_ctime))
            self.assertEqual(a_state.copy_policy, a_inode.copy_policy)
            self.assertEqual(
                a_state.block_size_shift,
                a_inode.block_size_shift)
            self.assertEqual(a_state.parent_vid, a_inode.parent_vdi_id)


if __name__ == '__main__':
    unittest.main()
