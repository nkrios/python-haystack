#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Search for a known structure type in a process memory. """

import logging
import pickle
import sys
import time
import subprocess
import json

import os

from haystack import basicmodel
from haystack.memory_mapper import MemoryHandlerFactory
from haystack.outputters import text
from haystack.outputters import python
from haystack.utils import xrange

__author__ = "Loic Jaquemet"
__copyright__ = "Copyright (C) 2012 Loic Jaquemet"
__email__ = "loic.jaquemet+python@gmail.com"
__license__ = "GPL"
__maintainer__ = "Loic Jaquemet"
__status__ = "Production"

log = logging.getLogger('abouchet')

if not sys.platform.startswith('win'):
    environSep = ':'
else:
    environSep = ';'


class StructFinder:

    """ Generic structure finder.
    Will search a structure defined by it's pointer and other constraints.
    Address space is defined by    _memory_handler.
    Target memory perimeter is defined by targetMappings.
    targetMappings is included in _memory_handler.

    :param mappings: address space
    :param targetMappings: search perimeter. If None, all _memory_handler are used in the search perimeter.
    """

    def __init__(self, mappings, targetMappings=None, updateCb=None):
        self.mappings = mappings
        if isinstance(mappings, bool):
            raise TypeError()
        self.targetMappings = targetMappings
        if targetMappings is None:
            self.targetMappings = mappings
        log.debug(
            'StructFinder on %d memorymappings. Search Perimeter on %d _memory_handler.' %
            (len(
                self.mappings), len(
                self.targetMappings)))
        return

    def find_struct(self, structType, hintOffset=0, maxNum=10, maxDepth=10):
        """ Iterate on all targetMappings to find a structure. """
        log.info(
            "Restricting search to %d memory mapping." %
            (len(
                self.targetMappings)))
        outputs = []
        for m in self.targetMappings:
            # debug, most structures are on head
            log.info("Looking at %s (%d bytes)" % (m, len(m)))
            # if not hasValidPermissions(m):
            #    log.warning("Invalid permission for memory %s. Stil looking at it"%m)
            #    #continue
            # else:
            #    log.debug("%s,%s"%(m,m.permissions))
            log.debug('look for %s' % (structType))
            outputs.extend(
                self.find_struct_in(
                    m,
                    structType,
                    hintOffset=hintOffset,
                    maxNum=maxNum,
                    maxDepth=maxDepth))
            # check out
            if len(outputs) >= maxNum:
                log.debug('Found enough instance. returning results.')
                break
        # if we mmap, we could yield
        return outputs

    def find_struct_in(
            self, memoryMap, structType, hintOffset=0, maxNum=10, maxDepth=99):
        """
            Looks for structType instances in memory, using :
                hints from structType (default values, and such)
                guessing validation with instance(structType)().isValid()
                and confirming with instance(structType)().loadMembers()

            returns POINTERS to structType instances.
        """
        import ctypes
        # update process _memory_handler
        log.debug(
            "scanning 0x%lx --> 0x%lx %s" %
            (memoryMap.start, memoryMap.end, memoryMap.pathname))

        # where do we look
        start = memoryMap.start
        end = memoryMap.end
        plen = ctypes.sizeof(ctypes.c_void_p)  # use aligned words only
        structlen = ctypes.sizeof(structType)
        # ret vals
        outputs = []
        # alignement
        if hintOffset in memoryMap:  # absolute offset
            align = hintOffset % plen
            start = hintOffset - align
        elif hintOffset != 0 and hintOffset < end - start:  # relative offset
            align = hintOffset % plen
            start = start + (hintOffset - align)

        # parse for structType on each aligned word
        log.debug(
            "checking 0x%lx-0x%lx by increment of %d" %
            (start, (end - structlen), plen))
        instance = None
        t0 = time.time()
        p = 0
        # xrange sucks. long int not ok
        for offset in xrange(start, end - structlen, plen):
            if offset % (1024 << 6) == 0:
                p2 = offset - start
                log.debug('processed %d bytes    - %02.02f test/sec' %
                          (p2, (p2 - p) / (plen * (time.time() - t0))))
                t0 = time.time()
                p = p2
            instance, validated = self.loadAt(
                memoryMap, offset, structType, maxDepth)
            if validated:
                log.debug("found instance @ 0x%lx" % (offset))
                # do stuff with it.
                outputs.append((instance, offset))
            if len(outputs) >= maxNum:
                log.debug(
                    'Found enough instance. returning results. find_struct_in')
                break
        return outputs

    def loadAt(self, memoryMap, offset, structType, depth=99):
        """
            loads a haystack ctypes structure from a specific offset.
                return (instance,validated) with instance being the haystack ctypes structure instance and validated a boolean True/False.
        """
        log.debug("Loading %s from 0x%lx " % (structType, offset))
        # instance=structType.from_buffer_copy(memoryMap.readStruct(offset,structType))
        instance = memoryMap.read_struct(offset, structType)
        # check if data matches
        if (instance.loadMembers(self.mappings, depth)):
            log.info("found instance %s @ 0x%lx" % (structType, offset))
            # do stuff with it.
            validated = True
        else:
            log.debug("Address not validated")
            validated = False
        return instance, validated


class VerboseStructFinder(StructFinder):

    """ structure finder with a update callback to be more verbose.
    Will search a structure defined by it's pointer and other constraints.
    Address space is defined by    _memory_handler.
    Target memory perimeter is defined by targetMappings.
    targetMappings is included in _memory_handler.

    :param mappings: address space
    :param targetMappings: search perimeter. If None, all _memory_handler are used in the search perimeter.
    :param updateCb: callback func. for periodic status update
    """

    def __init__(self, mappings, targetMappings=None, updateCb=None):
        StructFinder.__init__(self, mappings, targetMappings)
        self.updateCb = updateCb
        self._updateCb_init()

    def _updateCb_init(self):
        # approximation
        nb = lambda x: ((x.end - x.start) / 4)
        self._update_nb_steps = sum([nb(m) for m in self.targetMappings])
        self._update_i = 0

    def loadAt(self, memoryMap, offset, structType, depth=99):
        self._update_i += 1
        self.updateCb(self._update_i)
        StructFinder.loadAt(memoryMap, offset, structType, depth=depth)


def hasValidPermissions(memmap):
    """ memmap must be 'rw..' or shared '...s' """
    perms = memmap.permissions
    return (perms[0] == 'r' and perms[1] == 'w') or (perms[3] == 's')


def _callFinder(cmd_line):
    """ Call the haystack finder in a subprocess. Will use pickled objects to communicate results. """
    log.debug(cmd_line)
    env = os.environ
    # add possible pythonpaths to environnement
    env['PYTHONPATH'] = environSep.join(sys.path)
    p = subprocess.Popen(
        cmd_line,
        stdin=None,
        stdout=subprocess.PIPE,
        close_fds=True,
        env=env)
    p.wait()
    instance = p.stdout.read()
    instance = pickle.loads(instance)
    return instance


def getMainFile():
    # return os.path.abspath(sys.modules[__name__].__file__)
    return 'haystack'


def checkModulePath(typ):
    """
        add typ module's path to sys.path
        If the type is a generated haystack structure type,
        dump the '_generated' string from the module name and import it under the new module name.
    """
    name = typ.__name__
    module, sep, kname = name.rpartition('.')
    # add the __file__ module to sys.path for it to be reachable by subprocess
    moddir = os.path.dirname(sys.modules[typ.__module__].__file__)
    if moddir not in sys.path:
        sys.path.append(moddir)
    # check if it's a generated module
    if typ.__module__.endswith('_generated'):
        # try to import the ctypes_name to get aliases up and running
        # otherwise, pyObj will not be created, and the module will not be
        # registered in haystack model
        try:
            plainmod = typ.__module__.replace('_generated', '')
            mod = __import__(plainmod, globals(), locals(), [kname])
            structName = '.'.join([plainmod, kname])
            log.info('trying %s instead of %s' % (structName, name))
            return structName
        except ImportError:
            # shhh
            pass
    # we pass a str anyway...
    structName = '.'.join([typ.__module__, typ.__name__])
    return structName


def _find_struct(pid=None, memfile=None, memdump=None, structType=None, maxNum=1,
                fullScan=False, nommap=False, hint=None, debug=None, quiet=True):
    """
        Find all occurences of a specific structure from a process memory.
        Returns occurences as objects.

        Call a subprocess to ptrace a process. That way, self.process is not attached to the target PID by any means.

        :param pid is the process PID.
        :param memfile the file containing a direct dump of the memory mapping ( optionnal)
        :param memdump the file containing a memory dump
        :param structType the structure type.
        :param offset the offset from which the structure must be loaded.
        :param debug if True, activate debug logs.
        :param maxNum the maximum number of expected results. Searching will stop after that many findings. -1 is unlimited.
    """
    import ctypes
    if not isinstance(structType, type(ctypes.Structure)):
        raise TypeError('structType arg must be a ctypes.Structure')
    structName = checkModulePath(structType)  # add to sys.path
    cmd_line = [getMainFile(), "%s" % structName]
    if quiet:
        cmd_line.insert(2, "--quiet")
    elif debug:
        cmd_line.insert(2, "--debug")
    if nommap:
        cmd_line.insert(2, '--nommap')
    # three cases
    if pid:
        # live PID. with mmap or not
        cmd_line.extend(["--pid", "%d" % pid])
    elif memfile:
        # proc _memory_handler dump file
        cmd_line.extend(["--memfile", memfile])
    cmd_line.append('--pickled')
    # always add search
    cmd_line.extend(['search', '--maxnum', str(int(maxNum))])
    if fullScan:
        cmd_line.append('--fullscan')
    if hint:
        cmd_line.extend(['--hint', str(hex(hint))])
    # call me
    outs = _callFinder(cmd_line)
    if len(outs) == 0:
        log.error("The %s has not been found." % (structName))
        return None
    #
    return outs


def find_struct_process(pid, structType, maxNum=1, fullScan=False,
               nommap=False, debug=False, quiet=True):
    """
        Find all occurences of a specific structure from a process memory.

        :param pid is the process PID.
        :param structType the structure type.
        :param maxNum the maximum number of expected results. Searching will stop after that many findings. -1 is unlimited.
        :param fullScan obselete
        :param nommap if True, do not use mmap while searching.
        :param debug if True, activate debug logs.
    """
    return _find_struct(pid=pid, structType=structType, maxNum=maxNum,
                       fullScan=fullScan, nommap=nommap, debug=debug, quiet=quiet)


def find_struct_memfile(filename, structType, hint=None,
                     maxNum=1, fullScan=False, debug=False, quiet=True):
    """
        Find all occurences of a specific structure from a process memory in a file.

        :param filename is the file containing the memory mapping content.
        :param structType the structure type.
        :param maxNum the maximum number of expected results. Searching will stop after that many findings. -1 is unlimited.
        :param hint obselete
        :param fullScan obselete
        :param debug if True, activate debug logs.
    """
    return _find_struct(memfile=filename, structType=structType,
                       maxNum=maxNum, fullScan=fullScan, debug=debug, quiet=quiet)


def refresh_struct_process(pid, structType, offset, debug=False, nommap=False):
    """
        returns the pickled or text representation of a structure, from a given offset in a process memory.

        :param pid is the process PID.
        :param structType the structure Type.
        :param offset the offset from which the structure must be loaded.
        :param debug if True, activate debug logs.
        :param nommap if True, do not use mmap when mapping the memory
    """
    import ctypes
    if not isinstance(structType, type(ctypes.Structure)):
        raise TypeError('structType arg must be a ctypes.Structure')
    structName = checkModulePath(structType)  # add to sys.path
    cmd_line = [getMainFile(), '%s' % structName]
    if debug:
        cmd_line.insert(2, "--debug")
    if nommap:
        cmd_line.insert(2, '--nommap')
    # three cases
    if pid:
        # live PID. with mmap or not
        cmd_line.extend(["--pid", "%d" % pid])
    #elif memfile:
    #    # proc _memory_handler dump file
    #    cmd_line.extend(["--memfile", memfile])
    cmd_line.append('--pickled')
    # always add search
    cmd_line.extend(['refresh', "0x%lx" % offset])
    instance, validated = _callFinder(cmd_line)
    if not validated:
        log.error(
            "The session_state has not been re-validated. You should look for it again.")
        return None, None
    return instance, offset


class HaystackError(Exception):
    pass


def getKlass(name):
    """
        Returns the class type from a structure name.
        The class' module is dynamically loaded.

        :param name a haystack structure's text name. ( 'sslsnoop.ctypes_openssh.session_state' for example )
    """
    module, sep, kname = name.rpartition('.')
    mod = __import__(module, globals(), locals(), [kname])
    klass = getattr(mod, kname)

    log.debug('klass: %s' % (name))
    log.debug('module: %s' % (module))
    log.debug(getattr(mod, kname))
    #log.error(getattr(mod, kname+'_py'))
    return klass


def search_struct_mem(structName, mappings, targetMappings=None, maxNum=-1):
    """
        Search a structure in a specific memory mapping.

        if targetMappings is not specified, the search will occur in each memory _memory_handler
         in _memory_handler.

        :param structName the structure name.
        :param mappings the memory _memory_handler list.
        :param targetMappings the list of specific mapping to look into.
        :param maxNum the maximum number of results expected. -1 for infinite.
    """
    log.debug('searchIn: %s - %s' % (structName, mappings))
    structType = getKlass(structName)
    finder = StructFinder(mappings, targetMappings)
    # find all possible structType instance
    outs = finder.find_struct(structType, maxNum=maxNum)
    # prepare outputs
    parser = python.PythonOutputter(mappings)
    ret = [(parser.parse(ss), addr) for ss, addr in outs]
    if len(ret) > 0:
        log.debug("%s %s" % (ret[0], type(ret[0])))
    # TODO replace by instance method
    if basicmodel.findCtypesInPyObj(ret):
        log.error('=========************======= CTYPES STILL IN pyOBJ !!!! ')
    return ret


def search_struct_process(structName, pid, mmap=True, **kwargs):
    """Search a structure in the memory of a live process.

    :param structName the ctypes Structure
    :type structName string
    :param pid the process PID
    :param mmap flag to enable mmap syscalls (default)

    :param fullscan flag to extend search outside the heap
    :param hint an address hint to use as baseaddress for the search
                if given, the search will be limited to the mmap containing the hint adress
    :param rtype the return type format ( string, pickle, json )
    :type rtype ['string, pickle, json']

    :rtype either string, pickle object or json string or ( False, None )
    """
    structType = getKlass(structName)
    mappings = MemoryHandlerFactory(pid=pid, mmap=mmap).make_memory_handler()
    return _search(mappings, structType, **kwargs)


def search_struct_memfile(structName, memfile, baseOffset, **kwargs):
    """Search a structure in a raw memory file.

    :param structName the ctypes Structure
    :type structName string
    :param memfile the raw file memory dump
    :param baseOffset the baseOffset of the raw file memory dump

    :param fullscan flag to extend search outside the heap
    :param hint an address hint to use as baseaddress for the search
                if given, the search will be limited to the mmap containing the hint adress
    :param rtype the return type format ( string, pickle, json )
    :type rtype ['string, pickle, json']

    :rtype either string, pickle object or json string or ( False, None )
    """
    structType = getKlass(structName)
    mappings = MemoryHandlerFactory(
        memfile=memfile,
        baseOffset=baseOffset).make_memory_handler()
    return _search(mappings, structType, **kwargs)


def search_struct_dumpname(structName, dumpname, **kwargs):
    """Search a structure in the memory dump of a process.

    :param structName the ctypes Structure
    :type structName string
    :param dumpname the dump file

    :param fullscan flag to extend search outside the heap
    :param hint an address hint to use as baseaddress for the search
                if given, the search will be limited to the mmap containing the hint adress
    :param rtype the return type format ( string, pickle, json )
    :type rtype ['string, pickle, json']
    :rtype either string, pickle object or json string or ( False, None )
    """
    structType = getKlass(structName)
    mappings = MemoryHandlerFactory(dumpname=dumpname).make_memory_handler()
    return _search(mappings, structType, **kwargs)


def _search_cmdline(args):
    """ Internal cmdline mojo. """
    if args.volname is not None:
        mappings = MemoryHandlerFactory(
            pid=args.pid,
            volname=args.volname).make_memory_handler()
    elif args.pid is not None:
        mappings = MemoryHandlerFactory(pid=args.pid, mmap=args.mmap).make_memory_handler()
    elif args.dumpname is not None:
        mappings = MemoryHandlerFactory(dumpname=args.dumpname).make_memory_handler()
    elif args.memfile is not None:
        mappings = MemoryHandlerFactory(
            memfile=args.memfile,
            baseOffset=args.baseOffset).make_memory_handler()
    else:
        log.error('Nor PID, not memfile, not dumpname. What do you expect ?')
        raise RuntimeError(
            'Please validate the argparser. I couldnt find any useful information in your args.')
    # print output on stdout
    if args.human:
        rtype = 'string'
    elif args.json:
        rtype = 'json'
    elif args.pickled:
        rtype = 'pickled'
    d = {
        'fullscan': args.fullscan,
        'hint': args.hint,
        'interactive': args.interactive,
        'maxnum': args.maxnum}
    # delay loading of class after the customisation of ctypes by the memory
    # mapper
    structType = getKlass(args.structName)
    ret = _search(mappings, structType, rtype=rtype, **d)
    if isinstance(ret, list):
        for out in ret:
            print out
    return


def _search(mappings, structType, fullscan=False, hint=0,
            rtype='python', interactive=False, maxnum=1):
    """ make the search for structType    """
    # choose the search space
    if fullscan:
        targetMappings = mappings
    else:
        if hint:
            log.debug('Looking for the mmap containing the hint addr.')
            m = mappings.get_mapping_for_address(hint)
            if not m:
                log.error('This hint is not a valid addr (0x%x)' % (hint))
                raise ValueError(
                    'This hint is not a valid addr (0x%x)' %
                    (hint))
            targetMappings = [m]
        else:
            targetMappings = [mappings.get_heap()]
        # we don't want a Mappings instance, only a list
        if len(targetMappings) == 0:
            log.warning('No memorymapping found. Searching everywhere.')
            targetMappings = mappings
    # find the structure
    finder = StructFinder(mappings, targetMappings)
    outs = finder.find_struct(structType, hintOffset=hint, maxNum=maxnum)
    # DEBUG
    if interactive:
        import code
        code.interact(local=locals())
    # output genereration
    return _output(mappings, outs, rtype)


def _output(memory_handler, outs, rtype):
    """ Return results in the rtype format"""
    if len(outs) == 0:
        log.info('Found no occurence.')
        return None
    if rtype == 'string':
        outputter = text.RecursiveTextOutputter(memory_handler)
        ret = '['
        for ss, addr in outs:
            ret += "# --------------- 0x%lx \n%s" % (addr, outputter.parse(ss))
            pass
        ret += ']'
        return ret
    parser = python.PythonOutputter(memory_handler)
    ret = [(parser.parse(ss), addr) for ss, addr in outs]
    # last check to clean the structure from any ctypes Structure
    if python.findCtypesInPyObj(memory_handler,ret):
        raise HaystackError(
            'Bug in framework, some Ctypes are still in the return results. Please Report test unit.')
    # finally
    if rtype == 'python':  # pyobj
        return ret
    elif rtype == 'json':  # jsoned
        # cirular refs kills it check_circular=False,
        return json.dumps(ret, default=basicmodel.json_encode_pyobj)
    elif rtype == 'pickled':  # pickled
        return pickle.dumps(ret)
    return None


def _show_output(memory_handler, instance, validated, rtype):
    """ Return results in the rtype format.
    Results of non validated instance are not very interesting.
    """

    if rtype == 'string':
        if not validated:
            str_fn = lambda x: str(x)
        else:
            outputter = text.RecursiveTextOutputter(memory_handler)
            str_fn = lambda x: outputter.parse(x)
        return "(%s\n, %s)" % (str_fn(instance), validated)
    # else {'json', 'pickled', 'python'} : # cast in pyObject
    parser = python.PythonOutputter(memory_handler)
    pyObj = parser.parse(instance)
    # last check to clean the structure from any ctypes Structure
    if python.findCtypesInPyObj(memory_handler,pyObj):
        raise HaystackError(
            'Bug in framework, some Ctypes are still in the return results. Please Report test unit.')
    # finally
    if rtype == 'python':  # pyobj
        return (pyObj, validated)
    elif rtype == 'json':  # jsoned
        # cirular refs kills it check_circular=False,
        return json.dumps((pyObj, validated), default=python.json_encode_pyobj)
    elif rtype == 'pickled':  # pickled
        return pickle.dumps((pyObj, validated))

    raise ValueError('rtype should have a valid value')


def refresh(args):
    """
    Default function for the refresh command line option.
    Try to map a Structure from a specific offset in memory.
    Returns it in pickled or text format.

    See the command line --help .
    """
    log.debug(args)

    addr = int(args.addr, 16)

    mappings = MemoryHandlerFactory(
        pid=args.pid,
        memfile=args.memfile,
        dumpname=args.dumpname,
        volname=args.volname).make_memory_handler()
    finder = StructFinder(mappings)

    memoryMap = finder.mappings.is_valid_address_value(addr)
    if not memoryMap:
        log.error("the address is not accessible in the memoryMap")
        raise ValueError("the address is not accessible in the memoryMap")

    # delay loading of class after the customisation of ctypes by the memory
    # mapper
    structType = getKlass(args.structName)
    instance, validated = finder.loadAt(memoryMap,
                                        addr, structType)
    ##
    if args.interactive:
        import code
        code.interact(local=locals())

    if args.human:
        rtype = 'string'
    elif args.json:
        rtype = 'json'
    elif args.pickled:
        rtype = 'pickled'

    print _show_output(mappings, instance, validated, rtype)
    return


def show_dumpname(structname, dumpname, address, rtype='python'):
    """ shows the values for klass at @address in memdump.

    :param structname the ctypes structure name (string)
    :type structName string
    :param dumpname the memdump filename
    :param address the address from where to read the structure
    :param rtype the return type format ( string, pickle, json )
    :type rtype ['string', 'pickle', 'json', 'python']

    :returns (instance, validated) instance the loaded ctypes and validated a boolean flag
            if validated is True, all constraints were OK in instance.
    """
    from haystack import dump_loader
    log.debug('haystack show %s %s %x' % (dumpname, structname, address))
    mappings = dump_loader.load(dumpname)
    # delay loading of class after the customisation of ctypes by the memory
    # mapper
    structType = getKlass(structname)
    finder = StructFinder(mappings)
    # validate the input address.
    memoryMap = finder.mappings.is_valid_address_value(address)
    if not memoryMap:
        log.error("the address is not accessible in the memoryMap")
        raise ValueError("the address is not accessible in the memoryMap")
    instance, validated = finder.loadAt(memoryMap, address, structType)
    return _show_output(mappings, instance, validated, rtype)
