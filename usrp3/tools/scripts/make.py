#!/usr/bin/env python
"""
Copyright 2010-2011,2014-2015 Ettus Research LLC

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import print_function
import argparse
import os
import re
import glob

HEADER_TMPL = """/////////////////////////////////////////////////////////
// Auto-generated by gen_rfnoc_inst.py! Any changes
// in this file will be overwritten the next time
// this script is run.
/////////////////////////////////////////////////////////
localparam NUM_CE = {num_ce};
wire [NUM_CE*64-1:0] ce_flat_o_tdata, ce_flat_i_tdata;
wire [63:0]          ce_o_tdata[0:NUM_CE-1], ce_i_tdata[0:NUM_CE-1];
wire [NUM_CE-1:0]    ce_o_tlast, ce_o_tvalid, ce_o_tready, ce_i_tlast, ce_i_tvalid, ce_i_tready;
wire [63:0]          ce_debug[0:NUM_CE-1];
// Flattern CE tdata arrays
genvar k;
generate
  for (k = 0; k < NUM_CE; k = k + 1) begin
    assign ce_o_tdata[k] = ce_flat_o_tdata[k*64+63:k*64];
    assign ce_flat_i_tdata[k*64+63:k*64] = ce_i_tdata[k];
  end
endgenerate
wire ce_clk = radio_clk;
wire ce_rst = radio_rst;
"""

BLOCK_TMPL = """
noc_block_{blockname} {instname} (
  .bus_clk(bus_clk), .bus_rst(bus_rst),
  .ce_clk(ce_clk), .ce_rst(ce_rst),
  .i_tdata(ce_o_tdata[{n}]), .i_tlast(ce_o_tlast[{n}]), .i_tvalid(ce_o_tvalid[{n}]), .i_tready(ce_o_tready[{n}]),
  .o_tdata(ce_i_tdata[{n}]), .o_tlast(ce_i_tlast[{n}]), .o_tvalid(ce_i_tvalid[{n}]), .o_tready(ce_i_tready[{n}]),
  .debug(ce_debug[{n}])
);
"""

FILL_FIFO_TMPL = """
// Fill remaining crossbar ports with loopback FIFOs
genvar n;
generate
  for (n = {fifo_start}; n < NUM_CE; n = n + 1) begin
    noc_block_axi_fifo_loopback inst_noc_block_axi_fifo_loopback (
      .bus_clk(bus_clk), .bus_rst(bus_rst),
      .ce_clk(ce_clk), .ce_rst(ce_rst),
      .i_tdata(ce_o_tdata[n]), .i_tlast(ce_o_tlast[n]), .i_tvalid(ce_o_tvalid[n]), .i_tready(ce_o_tready[n]),
      .o_tdata(ce_i_tdata[n]), .o_tlast(ce_i_tlast[n]), .o_tvalid(ce_i_tvalid[n]), .o_tready(ce_i_tready[n]),
      .debug(ce_debug[n])
    );
  end
endgenerate
"""


def setup_parser():
    """
    Create argument parser
    """
    parser = argparse.ArgumentParser(
        description="Generate the NoC block instantiation file",
    )
    parser.add_argument(
        "-I", "--include-dir",
        help="Path directory of the RFNoC Out-of-Tree module",
        nargs='+',
        default=None)
    parser.add_argument(
        "-m", "--max-num-blocks", type=int,
        help="Maximum number of blocks (Max. Allowed for x310|x300: 10,\
                for e300: 6)",
        default=10)
    parser.add_argument(
        "--fill-with-fifos",
        help="If the number of blocks provided was smaller than the max\
                number, fill the rest with FIFOs",
        action="store_true")
    parser.add_argument(
        "-o", "--outfile",
        help="Output /path/filename - By running this directive,\
                you won't build your IP",
        default=None)
    parser.add_argument(
        "-d", "--device",
        help="Device to be programmed [x300, x310, e310]",
        default="x310")
    parser.add_argument(
        "-t", "--target",
        help="Build target - image type [X3X0_RFNOC_HG, X3X0_RFNOC_XG,\
                E310_RFNOC_sg3...]",
         default=None)
    parser.add_argument(
        "-g", "--GUI",
        help="Open Vivado GUI during the FPGA building process",
        action="store_true")
    parser.add_argument(
        "blocks",
        help="List block names to instantiate.",
        default="",
        nargs='*',
    )
    return parser

def create_vfiles(args):
    """
    Returns the verilogs
    """
    blocks = args.blocks
    if len(blocks) == 0:
        print("[GEN_RFNOC_INST ERROR] No blocks specified!")
        exit(1)
    if len(blocks) > args.max_num_blocks:
        print("[GEN_RFNOC_INST ERROR] Trying to connect {} blocks, max is {}".\
                format(len(blocks), args.max_num_blocks))
        exit(1)
    num_ce = args.max_num_blocks
    if not args.fill_with_fifos:
        num_ce = len(blocks)
    vfile = HEADER_TMPL.format(num_ce=num_ce)
    print("--Using the following blocks to generate image:")
    block_count = {k: 0 for k in set(blocks)}
    for i, block in enumerate(blocks):
        block_count[block] += 1
        instname = "inst_{}{}".format(block, "" \
                if block_count[block] == 1 else block_count[block])
        print("    * {}".format(block))
        vfile += BLOCK_TMPL.format(blockname=block, instname=instname, n=i)
    if args.fill_with_fifos:
        vfile += FILL_FIFO_TMPL.format(fifo_start=len(blocks))
    return vfile

def file_generator(args, vfile):
    """
    Takes the target device as an argument and, if no '-o' directive is given,
    replaces the auto_ce file in the corresponding top folder. With the
    presence of -o, it just generates a version of the verilog file which
    is  not intended to be build
    """
    fpga_utils_path = get_scriptpath()
    print("Adding CE instantiation file for '%s'" % args.target)
    path_to_file = fpga_utils_path +'/../../top/' + device_dict(args.device.lower()) +\
            '/rfnoc_ce_auto_inst_' + args.device + '.v'
    if args.outfile is None:
        open(path_to_file, 'w').write(vfile)
    else:
        open(args.outfile, 'w').write(vfile)

def append_re_line_sequence(filename, linepattern, newline):
    """ Detects the re 'linepattern' in the file. After its last occurrence,
    paste 'newline'. If the pattern does not exist, append the new line
    to the file. Then, write. If the newline already exists, leaves the file
    unchanged"""
    oldfile = open(filename, 'r').read()
    lines = re.findall(newline, oldfile, flags=re.MULTILINE)
    if len(lines) != 0:
        pass
    else:
        pattern_lines = re.findall(linepattern, oldfile, flags=re.MULTILINE)
        if len(pattern_lines) == 0:
            open(filename, 'a').write(newline)
            return
        last_line = pattern_lines[-1]
        newfile = oldfile.replace(last_line, last_line + newline + '\n')
        open(filename, 'w').write(newfile)

def append_item_into_file(args):
    """
    Basically the same as append_re_line_sequence function, but it does not
    append anything when the input is not found
    ---
    Detects the re 'linepattern' in the file. After its last occurrence,
    pastes the input string. If pattern doesn't exist
    notifies and leaves the file unchanged
    """

    target_dir = device_dict(args.device.lower())
    if args.include_dir is not None:
        for dirs in args.include_dir:
            checkdir_v(dirs)
            oot_srcs_file = os.path.join(dirs, 'Makefile.srcs')
            dest_srcs_file = os.path.join(get_scriptpath(), '..', '..', 'top',\
                    target_dir, 'Makefile.srcs')
            prefixpattern = re.escape('$(addprefix ' + dirs + ', \\\n')
            linepattern = re.escape('RFNOC_OOT_SRCS = \\\n')
            oldfile = open(dest_srcs_file, 'r').read()
            prefixlines = re.findall(prefixpattern, oldfile, flags=re.MULTILINE)
            if len(prefixlines) == 0:
                lines = re.findall(linepattern, oldfile, flags=re.MULTILINE)
                if len(lines) == 0:
                    print("Pattern {} not found. Could not write {} file".\
                            format(linepattern, oldfile))
                    return
                else:
                    last_line = lines[-1]
                    srcs = "".join(readfile(oot_srcs_file))
            else:
                last_line = prefixlines[-1]
                srcs = "".join(compare(oot_srcs_file, dest_srcs_file))
            newfile = oldfile.replace(last_line, last_line + srcs)
            open(dest_srcs_file, 'w').write(newfile)

def compare(file1, file2):
    """
    compares two files line by line, and returns the lines of first file that
    were not found on the second. The returned is a tuple item that can be
    accessed in the form of a list as tuple[0], where each line takes a
    position on the list or in a string as tuple [1].
    """
    notinside = []
    with open(file1, 'r') as arg1:
        with open(file2, 'r') as arg2:
            text1 = arg1.readlines()
            text2 = arg2.readlines()
            for item in text1:
                if item not in text2:
                    notinside.append(item)
    return notinside

def readfile(files):
    """
    compares two files line by line, and returns the lines of first file that
    were not found on the second. The returned is a tuple item that can be
    accessed in the form of a list as tuple[0], where each line takes a
    position on the list or in a string as tuple [1].
    """
    contents = []
    with open(files, 'r') as arg:
        text = arg.readlines()
        for item in text:
            contents.append(item)
    return contents

def build(args):
    " build "
    cwd = get_scriptpath()
    target_dir = device_dict(args.device.lower())
    build_dir = os.path.join(cwd, '..', '..', 'top', target_dir)
    if os.path.isdir(build_dir):
        print("changing temporarily working directory to {0}".\
                format(build_dir))
        os.chdir(build_dir)
        make_cmd = "source ./setupenv.sh && make " + dtarget(args)
        if(args.GUI):
            make_cmd = make_cmd + " GUI=1"
        ret_val = os.system(make_cmd)
        os.chdir(cwd)
    return ret_val

def device_dict(args):
    """
    helps selecting the device building folder based on the targeted device
    """
    build_dir = {'x300':'x300', 'x310':'x300', 'e300':'e300', 'e310':'e300'}
    return build_dir[args]

def dtarget(args):
    """
    If no target specified,  selecs the default building target based on the
    targeted device
    """
    if args.target is None:
        default_trgt = {'x300':'X300_RFNOC_HG', 'x310':'X310_RFNOC_HG',\
                'e310':'E310_RFNOC_HLS'}
        return default_trgt[args.device]
    else:
        return args.target

def checkdir_v(include_dir):
    """
    Checks the existance of verilog files in the given include dir
    """
    nfiles = glob.glob(include_dir+'*.v')
    if len(nfiles) == 0:
        print('[ERROR] No verilog files found in the given directory')
        exit(0)
    else:
        print('Verilog sources found!')
    return

def get_scriptpath():
    """
    returns the absolute path where a script is located
    """
    return os.path.dirname(os.path.realpath(__file__))

def main():
    " Go, go, go! "
    args = setup_parser().parse_args()
    vfile = create_vfiles(args)
    file_generator(args, vfile)
    append_item_into_file(args)
    if args.outfile is  None:
        return build(args)
    else:
        print("Instantiation file generated at {}".\
                format(args.outfile))
        return 0

if __name__ == "__main__":
    exit(main())

