#!/usr/bin/env python
'''
Short script to make OPL music (in DOSBox DRO files) less loud.

More information on DRO and OPL:

* https://zdoom.org/wiki/DRO
* http://www.shikadi.net/moddingwiki/DRO_Format
* http://www.fit.vutbr.cz/~arnost/opl/opl3.html

(C) Michiel Sikma <michiel@sikma.org>. MIT licensed.
'''
from struct import *
from stat import *
from collections import namedtuple
from math import ceil
from datetime import timedelta
from os import path
from math import log2
import os
import time
import sys
import argparse

CARRIERS = (0x43, 0x44, 0x45, 0x4B, 0x4C, 0x4D, 0x53, 0x54, 0x55)
LEVEL_TO_ALGORITHM = {
    0x40: 0xC0, 0x41: 0xC0, 0x42: 0xC1, 0x43: 0xC1, 0x44: 0xC2, 0x45: 0xC2,
    0x48: 0xC3, 0x49: 0xC3, 0x4A: 0xC4, 0x4B: 0xC4, 0x4C: 0xC5, 0x4D: 0xC5,
    0x50: 0xC6, 0x51: 0xC6, 0x52: 0xC7, 0x53: 0xC7, 0x54: 0xC8, 0x55: 0xC8
}
HARDWARE_TYPES = {
    0: 'OPL2',
    1: 'Dual OPL2',
    2: 'OPL3'
}
FORMAT_TYPES = {
    0: 'Commands and data interleaved',
    1: '(unknown)'
}
COMPRESSION_TYPES = {
    # only one in use currently
    0: 'No compression'
}
FILESIZE_SUFFIXES = [
    'bytes', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB'
]

def file_size(size):
    '''
    Returns a filesize in human-readable format.
    <https://stackoverflow.com/a/25613067>
    '''
    order = int(log2(size) / 10) if size else 0
    return ('{:.4g} {}'
        .format(size / (1 << (order * 10)), FILESIZE_SUFFIXES[order]))

def namedunpack(data, names, format):
    '''
    Unpacks into a named tuple.
    '''
    str = namedtuple('struct', names)
    data = str(*unpack(format, data))
    return data

def print_info(infile_n, data, codemap, verbose):
    '''
    Prints file information for a DRO file.
    '''
    st = os.stat(infile_n)
    bytes = st[ST_SIZE]
    mod_time = time.asctime(time.localtime(st[ST_MTIME]))
    print('Filename:       {}'.format(infile_n))
    print('Size:           {} ({} bytes)'.format(file_size(bytes), bytes))
    print('Modified:       {}'.format(mod_time))
    print('')
    print('DRO version:    {}.{}'
        .format(data.iVersionMajor, data.iVersionMinor))
    print('Length:         {} ({} ms, {} register/value pairs)'
        .format(
            str(timedelta(0, 0, 0, data.iLengthMS))[:-3],
            data.iLengthMS,
            data.iLengthPairs
        ))
    print('Hardware:       {} (id={})'
        .format(HARDWARE_TYPES[data.iHardwareType], data.iHardwareType))
    print('Format:         {} (id={})'
        .format(FORMAT_TYPES[data.iFormat], data.iFormat))
    print('Compression:    {} (id={})'
        .format(COMPRESSION_TYPES[data.iCompression], data.iCompression))
    print('Delay codes:    {}/0x{:02X} (short)'
        .format(data.iShortDelayCode, data.iShortDelayCode))
    print('                {}/0x{:02X} (long)'
        .format(data.iLongDelayCode, data.iLongDelayCode))
    print('Codemap table:  {} entries'
        .format(data.iCodemapLength))
    
    if not verbose:
        return
    
    print('')

    # Now print the complete codemap table.
    entries = data.iCodemapLength - 1
    cols = 6
    rows = ceil(entries / cols)
    for n in range(rows):
        for m in range(cols):
            l = n + m * rows
            if l > entries: break
            r = codemap[l]
            print('0x{:02X}: 0x{:02X}   '.format(l, r), end='')
        print('')

class OPL2Quieter(object):
    '''
    Class for reducing the volume of OPL commands.
    '''
    def __init__(self, quiet_function):
        self.quiet_function = quiet_function
        self.registers = [0x00 for i in range(0x100)]
    
    def write(self, register, value):
        if 0x40 <= register <= 0x55:  # If it is a level register
            # Algorithm bit is the LSB of algorithm/feedback register.
            algorithm = self.registers[LEVEL_TO_ALGORITHM[register]] & 0x01
            
            if algorithm == 0x00:
                # FM synthesis, only modify the level if it's a carrier.
                modify_level = True if register in CARRIERS else False
            else:
                # AM synthesis, modify level for both operators.
                modify_level = True
            
            if modify_level:
                # Keep the top two bits (the KSL value) separate
                # for purposes of calculation.
                ksl = value & 0xC0
                # Perform the volume modification on the lower six bits.
                level = self.quiet_function(value & 0x3F)
                value = ksl | (level & 0x3F)
        
        self.registers[register] = value
        return register, value

def quieter_main(infile_n, outfile_n, overwrite, verbose, level, silent=True):
    '''
    The main program: runs the quieter code on the input file.
    It also runs all the necessary checks to ensure that we can read
    and write, and prints debugging information if requested.
    
    Returns an exit code, and an exit reason if the exit code is >0.
    '''
    # Redirect all output to the null device if we're in silent mode.
    if silent:
        sys.stdout = open(os.devnull, 'w')
    if not path.isfile(infile_n):
        return (1, 'input file does not exist.')
    if path.isfile(outfile_n) and not overwrite:
        return (1, 'output file exists and --overwrite is not set.')

    try:
        infile = open(infile_n, 'rb')
    except IOError:
        return (1, 'could not open input file.')
    try:
        outfile = open(outfile_n, 'wb')
    except IOError:
        return (1, 'could not open output file.')
    
    chunk = infile.read(26)
    values = [
        'cSignature', 'iVersionMajor', 'iVersionMinor', 'iLengthPairs',
        'iLengthMS', 'iHardwareType', 'iFormat', 'iCompression',
        'iShortDelayCode', 'iLongDelayCode', 'iCodemapLength'
    ]
    data = namedunpack(chunk, values, '8sHHIIBBBBBB')
    short_delay = data.iShortDelayCode
    long_delay = data.iLongDelayCode
    outfile.write(chunk)

    if data.cSignature != b'DBRAWOPL':
        return (1, 'input file is not a valid DOSBox DRO file.')
    
    # Copy over the codemap table, which has a variable length.
    codemap = infile.read(data.iCodemapLength)
    outfile.write(codemap)

    # Print file information for debugging.
    try:
        print_info(infile_n, data, codemap, verbose)
    except IOError:
        parser.error('could not stat input file.')

    print('\nReducing volume by {} levels.'.format(level))
    if verbose:
        print('Reading DRO file and logging events.')
    pairsTotal = data.iLengthPairs
    pairsRead = 0
    quieter = OPL2Quieter(lambda level: max(level - level, 0))
    while pairsRead < pairsTotal:
        # Read the next OPL bytes from the file.
        # The first byte is the register, and the second is the value.
        chunk = infile.read(2)
        if not chunk: break
        reg, val = unpack('BB', chunk)
        # Keep the register value before we look it up in the codemap table.
        orig_reg = reg
    
        # If the register's value is over 0x80, it applies to bank 1.
        if reg & 0x80:
            bank = 1
            reg ^= 0x80
        else:
            bank = 0

        # If the register corresponds to the short or long delay values,
        # don't look up their values in the codemap.
        # Also, display them differently in the output.
        if reg == short_delay:
            reg_print = 'DLYS'
            skip_quieter = True
        elif reg == long_delay:
            reg_print = 'DLYL'
            skip_quieter = True
        else:
            reg = codemap[reg]
            reg_print = '0x{:02X}'.format(reg)
            skip_quieter = False
    
        # Check whether our quieter will change the value.
        # If so, print the change.
        val_before = val
    
        # Run our values through the quieter, unless it's a delay.
        if not skip_quieter:
            reg, val = quieter.write(reg, val)
        
        outfile.write(pack('BB', orig_reg, val))
        pairsRead += 1
    
        # Print debugging information.
        if verbose:
            print('Pos: {:05d}   Bank: {:01d}   Reg: {}   Val: 0x{:02X}'
                .format(pairsRead, bank, reg_print, val), end='')
            if val != val_before:
                print(' -> 0x{:02X}'.format(val), end='')
            print('')

    infile.close()
    outfile.close()
    if verbose: print('')
    print('Wrote new DRO file: {}'.format(outfile_n))
    return (0,)

def run_cli():
    '''
    Runs the program from the command line.
    '''
    parser = argparse.ArgumentParser(
        description='Reduces the volume of a DOSBox DRO file.'
    )
    parser.add_argument('infile', help='input file', type=str)
    parser.add_argument('outfile', help='output file', type=str)
    parser.add_argument('-v', '--verbose',
        help='print extra file/progress information',
        action='store_true')
    parser.add_argument('-o', '--overwrite',
        help='overwrite output file if it already exists',
        action='store_true')
    parser.add_argument('-s', '--silent',
        help='disables all info and error messages',
        action='store_true')
    parser.add_argument('--level',
        help='amount of quieting (default: 5)',
        default=5,
        type=int)
    args = parser.parse_args()
    
    # If we're here, that means all command line arguments were valid.
    # Run the main program and collect its return value.
    exit_code = quieter_main(args.infile, args.outfile, args.overwrite,
        args.verbose, args.level, args.silent)
    
    # If the return value is 1, print an error message.
    if exit_code[0] == 1:
        parser.error(exit_code[1])
    sys.exit(exit_code[0])

if __name__ == '__main__':
    run_cli()
