# -*- coding: utf-8 -*-

import logging
import pickle
import json

from haystack.search import searcher
from haystack import constraints
from haystack.outputters import text
from haystack.outputters import python

log = logging.getLogger('api')

class HaystackError(Exception):
    pass

def search_record(memory_handler, struct_type, search_constraints=None):
    """
    Search a record in the memory dump of a process represented
    by memory_handler.

    the record type must have been imported using haystack functions.

    if constraints exists, they will be considered during the search.

    :param memory_handler: IMemoryHandler
    :param struct_type: a ctypes.Structure or ctypes.Union from a module imported by haystack
    :param search_constraints: IConstraintDict to be considered during the search
    :rtype a list of (ctypes records, memory offset)
    """
    my_searcher = searcher.RecordSearcher(memory_handler)
    if search_constraints is not None:
        # get module from module name struct_type.__module__ from model.
        module = memory_handler.get_model().get_imported_module(struct_type.__module__)
        constraints.apply_to_module(search_constraints, module)
    return my_searcher.search(struct_type)

def output_to_string(memory_handler, results):
    """
    Transform ctypes results in a string format
    :param memory_handler: IMemoryHandler
    :param results: results from the search_record
    :return:
    """
    if not isinstance(results, list):
        raise TypeError('Feed me a list of results')
    parser = text.RecursiveTextOutputter(memory_handler)
    ret = '['
    for ss, addr in results:
        ret += "# --------------- 0x%lx \n%s" % (addr, parser.parse(ss))
        pass
    ret += ']'
    return ret

def output_to_python(memory_handler, results):
    """
    Transform ctypes results in a non-ctypes python object format
    :param memory_handler: IMemoryHandler
    :param results: results from the search_record
    :return:
    """
    if not isinstance(results, list):
        raise TypeError('Feed me a list of results')
    # also generate POPOs
    my_model = memory_handler.get_model()
    pythoned_modules = my_model.get_pythoned_modules().keys()
    for module_name, module in my_model.get_imported_modules().items():
        if module_name not in pythoned_modules:
            my_model.build_python_class_clones(module)
    # parse and generate instances
    parser = python.PythonOutputter(memory_handler)
    ret = [(parser.parse(ss), addr) for ss, addr in results]
    # last check to clean the structure from any ctypes Structure
    if python.findCtypesInPyObj(memory_handler, ret):
        raise HaystackError(
            'Bug in framework, some Ctypes are still in the return results. Please Report test unit.')
    return ret

def output_to_json(memory_handler, results):
    """
    Transform ctypes results in a json format
    :param memory_handler: IMemoryHandler
    :param results: results from the search_record
    :return:
    """
    if not isinstance(results, list):
        raise TypeError('Feed me a list of results')
    ret = output_to_python(memory_handler, results)
    # cirular refs kills it check_circular=False,
    return json.dumps(ret, default=python.json_encode_pyobj)

def output_to_pickle(memory_handler, results):
    """
    Transform ctypes results in a pickled format
    :param memory_handler: IMemoryHandler
    :param results: results from the search_record
    :return:
    """
    if not isinstance(results, list):
        raise TypeError('Feed me a list of results')
    ret = output_to_python(memory_handler, results)
    return pickle.dumps(ret)

def load_record(memory_handler, struct_type, memory_address):
    """
    Load a record from a specific address in memory.
    You could use that function to monitor a specific record from memory after a refresh.

    :param memory_handler: IMemoryHandler
    :param struct_type: a ctypes.Structure or ctypes.Union
    :param memory_address: long
    :return: (ctypes record instance, validated_boolean)
    """
    if not isinstance(memory_address, long) and not isinstance(memory_address, int):
        raise TypeError('Feed me a long memory_address')
    my_loader = searcher.RecordLoader(memory_handler)
    return my_loader.load(struct_type, memory_address)
