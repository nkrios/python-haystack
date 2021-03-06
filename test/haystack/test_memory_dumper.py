#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests haystack.utils ."""

from __future__ import print_function

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from haystack import memory_dumper

__author__ = "Loic Jaquemet"
__copyright__ = "Copyright (C) 2012 Loic Jaquemet"
__email__ = "loic.jaquemet+python@gmail.com"
__license__ = "GPL"
__maintainer__ = "Loic Jaquemet"
__status__ = "Production"


class TestMemoryDumper(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # run make.py
        import os

        if not os.geteuid() == 0:
            #raise RuntimeError(
            raise unittest.SkipTest(
                "MemoryHandler dump test can only be run as root. Please sudo")

    def get_folder_size(self, folder):
        folder_size = 0
        for (path, dirs, files) in os.walk(folder):
            for file in files:
                filename = os.path.join(path, file)
                folder_size += os.path.getsize(filename)
        return folder_size

    def run_app_test(self, testName, stdout=sys.stdout):
        if testName not in self.tests:
            raise ValueError(
                "damn, please choose testName in %s" %
                (self.tests.keys()))
        appname = self.tests[testName]
        srcDir = os.path.sep.join([os.getcwd(), 'test', 'src'])
        tgt = os.path.sep.join([srcDir, appname])
        if not os.access(tgt, os.F_OK):
            print('\nCould not find test binaries', tgt)
            print('HAVE YOU BUILD THEM ?')
            raise IOError
        return subprocess.Popen([tgt], stdout=stdout)


class TestMemoryDumper32(TestMemoryDumper):

    """Tests MemoryDumper with 3 format types.

    Tests :
    for each format,
        launch a process
        dump the heap
        kill the process
        launch a process
        dump the heap and stack
        kill the process
        launch a process
        dump all the memory _memory_handler
        kill the process
        compare size which should be incremental
        compare _memory_handler files which should be the same
    """

    def setUp(self):
        from haystack import types
        types.build_ctypes_proxy(4, 4, 8)
        self.cpu_bits = '32'
        self.os_name = 'linux'
        self.tgts = []
        self.process = None
        self.tests = {"test1": "test-ctypes1.%d" % (32),
                      "test2": "test-ctypes2.%d" % (32),
                      "test3": "test-ctypes3.%d" % (32),
                      }

    def tearDown(self):
        if self.process is not None:
            try:
                self.process.kill()
            except OSError as e:
                pass
        for f in self.tgts:
            if os.path.isfile(f):
                os.remove(f)
            elif os.path.isdir(f):
                shutil.rmtree(f)

    def _make_tgt_dir(self):
        tgt = tempfile.mkdtemp()
        self.tgts.append(tgt)
        return tgt

    def _renew_process(self):
        self.process.kill()
        self.process = self.run_app_test('test3', stdout=self.devnull.fileno())
        time.sleep(0.1)

    def test_mappings_file(self):
        '''Checks if memory_dumper make a _memory_handler index file'''
        tgt1 = self._make_tgt_dir()
        self.devnull = open('/dev/null')
        self.process = self.run_app_test('test1', stdout=self.devnull.fileno())
        time.sleep(0.1)
        # FIXME, heaponly is breaking machine detection.
        out1 = memory_dumper.dump(self.process.pid, tgt1, "dir", True)
        self.assertIsNotNone(open('%s/_memory_handler' % out1))
        self.assertGreater(len(
            open('%s/_memory_handler' % out1).readlines()), 15, 'the _memory_handler file looks too small')

    def test_dumptype_dir(self):
        '''Checks if dumping to folder works'''
        tgt1 = self._make_tgt_dir()
        tgt2 = self._make_tgt_dir()
        tgt3 = self._make_tgt_dir()

        self.devnull = open('/dev/null')
        self.process = self.run_app_test('test3', stdout=self.devnull.fileno())
        time.sleep(0.1)
        out1 = memory_dumper.dump(self.process.pid, tgt1, "dir", True)
        self.assertEqual(out1, tgt1)  # same name

        self._renew_process()
        out2 = memory_dumper.dump(self.process.pid, tgt2, "dir", True)
        self.assertEqual(out2, tgt2)  # same name

        self._renew_process()
        out3 = memory_dumper.dump(self.process.pid, tgt3, "dir", False)
        self.assertEqual(out3, tgt3)  # same name

        size1 = self.get_folder_size(tgt1)
        size2 = self.get_folder_size(tgt2)
        size3 = self.get_folder_size(tgt3)

        self.assertGreater(size1, 500)  # not a null archive
        # self.assertGreater(size2, size1) # more _memory_handler
        self.assertGreater(size3, size2)  # more _memory_handler
        # print size1, size2, size3
        # print file(out1+'/_memory_handler').read()
        # print '-'*80
        # print file(out2+'/_memory_handler').read()
        # print '-'*80
        # print file(out3+'/_memory_handler').read()
        # print '-'*80

        # test opening by dump_loader
        from haystack.mappings import folder
        from haystack.mappings.base import MemoryHandler
        # PYDOC
        # NotImplementedError: MACHINE has not been found.
        # laoder should habe a cpu, os_name loading
        mappings1 = folder.load(
            out1,
            cpu=self.cpu_bits,
            os_name=self.os_name)
        self.assertIsInstance(mappings1, MemoryHandler)

        mappings2 = folder.load(
            out2,
            cpu=self.cpu_bits,
            os_name=self.os_name)
        mappings3 = folder.load(
            out3,
            cpu=self.cpu_bits,
            os_name=self.os_name)

        pathnames1 = [m.pathname for m in mappings1]
        pathnames2 = [m.pathname for m in mappings2]
        pathnames3 = [m.pathname for m in mappings3]
        self.assertEqual(pathnames1, pathnames2)
        self.assertEqual(pathnames3, pathnames2)

        return

    def _setUp_known_pattern(self, compact=True):
        self.devnull = open('/dev/null')
        self.process = self.run_app_test('test3', stdout=subprocess.PIPE)
        time.sleep(0.1)
        tgt = self._make_tgt_dir()
        self.out = memory_dumper.dump(self.process.pid, tgt, 'dir', compact)
        self.process.kill()
        return self.process.communicate()

    def test_known_pattern_python(self):
        (stdoutdata, stderrdata) = self._setUp_known_pattern(compact=False)
        # get offset from test program
        offsets_1 = [l.split(' ')[1]
                     for l in stdoutdata.split('\n') if "test1" in l]
        offsets_3 = [l.split(' ')[1]
                     for l in stdoutdata.split('\n') if "test3" in l]
        # check offsets in memory dump
        import haystack.api
        for offset in offsets_1:
            instance, found = haystack.api.show_dumpname(
                'test.src.ctypes3.struct_Node', self.out, int(
                    offset, 16), rtype='python')
            self.assertTrue(found)
            self.assertEqual(instance.val1, 0xdeadbeef)
            self.assertNotEquals(instance.ptr2, 0x0)
            pass

        for offset in offsets_3:
            instance, found = haystack.api.show_dumpname(
                'test.src.ctypes3.struct_test3', self.out, int(
                    offset, 16), rtype='python')
            self.assertTrue(found)
            self.assertEqual(instance.val1, 0xdeadbeef)
            self.assertEqual(instance.val1b, 0xdeadbeef)
            self.assertEqual(instance.val2, 0x10101010)
            self.assertEqual(instance.val2b, 0x10101010)
            pass

    def test_known_pattern_string(self):
        (stdoutdata, stderrdata) = self._setUp_known_pattern(compact=False)
        # get offset from test program
        offsets_1 = [l.split(' ')[1]
                     for l in stdoutdata.split('\n') if "test1" in l]
        offsets_3 = [l.split(' ')[1]
                     for l in stdoutdata.split('\n') if "test3" in l]
        # check offsets in memory dump
        import haystack.api
        for offset in offsets_3:
            ret = haystack.api.show_dumpname(
                'test.src.ctypes3.struct_test3', self.out, int(
                    offset, 16), rtype='string')
            self.assertIn('"val1": 3735928559L', ret)
            self.assertIn('"val2": 269488144L', ret)
            self.assertIn('"val2b": 269488144L', ret)
            self.assertIn('"val1b": 3735928559L', ret)
            self.assertIn('True', ret)
            pass

    def test_known_pattern_json(self):
        (stdoutdata, stderrdata) = self._setUp_known_pattern(compact=False)
        # get offset from test program
        offsets_1 = [l.split(' ')[1]
                     for l in stdoutdata.split('\n') if "test1" in l]
        offsets_3 = [l.split(' ')[1]
                     for l in stdoutdata.split('\n') if "test3" in l]
        # check offsets in memory dump
        import haystack.api
        for offset in offsets_3:
            self.assertRaises(ValueError,
                              haystack.api.show_dumpname,
                              'test.src.ctypes3.struct_test3',
                              self.out,
                              int(offset,
                                  16),
                              rtype='json')
            pass


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    # logging.basicConfig(level=logging.DEBUG)
    unittest.main(verbosity=2)
