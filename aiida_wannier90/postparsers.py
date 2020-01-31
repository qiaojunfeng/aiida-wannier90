# -*- coding: utf-8 -*-
from __future__ import absolute_import
import io
import os
import six
from six.moves import range
from aiida.parsers import Parser
from aiida.common import exceptions as exc


class PostWannier90Parser(Parser):
    """
    post Wannier90 output parser. Will parse global gauge invarient spread as well as
    the centers, spreads and, if possible the Imaginary/Real ratio of the
    wannier functions. Will also check to see if the output converged.
    """
    def __init__(self, node):
        from .calculations import Wannier90Calculation

        # check for valid input
        if not issubclass(node.process_class, Wannier90Calculation):
            raise exc.OutputParsingError(
                "Input must calc must be a "
                "Wannier90Calculation, it is instead {}".format(
                    type(node.process_class)
                )
            )
        super(PostWannier90Parser, self).__init__(node)

    def parse(self, **kwargs):
        """
        Parses the datafolder, stores results.
        This parser for this simple code does simply store in the DB a node
        representing the file of forces in real space
        """
        from aiida.orm import Dict, SinglefileData

        seedname = self.node.get_options()['seedname']
        output_file_name = "{}.wpout".format(seedname)
        error_file_name = "{}.werr".format(seedname)

        # select the folder object
        # Check that the retrieved folder is there
        try:
            out_folder = self.retrieved
        except exc.NotExistent:
            return self.exit_codes.ERROR_NO_RETRIEVED_FOLDER

        # Checks for error output files
        if error_file_name in out_folder.list_object_names():
            self.logger.error(
                'Errors were found please check the retrieved '
                '{} file'.format(error_file_name)
            )
            return self.exit_codes.ERROR_WERR_FILE_PRESENT

        exiting_in_stdout = False
        try:
            with out_folder.open(output_file_name) as handle:
                out_file = handle.readlines()
            # Wannier90 doesn't always write the .werr file on error
            if any('Exiting......' in line for line in out_file):
                exiting_in_stdout = True
        except OSError:
            self.logger.error("Standard output file could not be found.")
            return self.exit_codes.ERROR_OUTPUT_STDOUT_MISSING

        # Tries to parse the dos
        try:
            dos = self.node.inputs.dos
            with out_folder.open('{}-dos.dat'.format(seedname)) as fil:
                band_dat_file = fil.readlines()
        except (exc.NotExistent, KeyError, IOError):
            # exc.NotExistent: no input dos
            # KeyError: no get_dict()
            # IOError: _band.* files not present
            pass
        else:
            ## TODO: should we catch exceptions here?
            output_dos = dos_parser(band_dat_file)
            self.out('output_dos', output_dos)

        # Parse the stdout an return the parsed data
        wpout_dictionary = raw_wpout_parser(out_file)
        output_data = Dict(dict=wpout_dictionary)
        self.out('output_parameters', output_data)

        if exiting_in_stdout:
            return self.exit_codes.ERROR_EXITING_MESSAGE_IN_STDOUT


def raw_wpout_parser(wann_out_file):
    '''
    This section will parse a .wpout file and return certain key
    parameters such as the centers and spreads of the
    wannier90 functions, the Im/Re ratios, certain warnings,
    and labels indicating output files produced

    :param out_file: the .wout file, as a list of strings
    :return out: a dictionary of parameters that can be stored as parameter data
    '''
    out = {}
    out.update({'warnings': []})
    for i in range(len(wann_out_file)):
        line = wann_out_file[i]
        # checks for any warnings
        if 'Warning' in line:
            # Certain warnings get a special flag
            out['warnings'].append(line)

        # From the 'initial' part of the output, only sections which indicate
        # whether certain files have been written, e.g. 'Write r^2_nm to file'
        # the units used, e.g. 'Length Unit', that will guide the parser
        # e.g. 'Number of Wannier Functions', or which supplament warnings
        # not directly provided, e.g. unconvergerged wannierization needs
        # some logic in AiiDa to determine whether it met the convergence
        # target or not...

        # Parses some of the POSTW90 parameters
        # There should be only one POSTW90, no repeated run
        if 'POSTW90' in line:
            i += 1
            line = wann_out_file[i]
            while '-----' not in line:
                line = wann_out_file[i]
                if 'Number of Wannier Functions' in line:
                    out.update({
                        'number_wannier_functions':
                        int(line.split()[-2])
                    })
                if 'Number of electrons per state' in line:
                    out.update({
                        'number_electrons_per_state':
                        int(line.split()[-2])
                    })
                if 'Fermi energy (eV)' in line:
                    out.update({
                        'fermi_energy':
                        int(line.split()[-2])
                    })
                if 'Length Unit' in line:
                    out.update({'length_units': line.split()[-2]})
                    if (out['length_units'] != 'Ang'):
                        out['warnings'].append(
                            'Units not Ang, '
                            'be sure this is OK!'
                        )

                if 'Output verbosity (1=low, 5=high)' in line:
                    out.update({'output_verbosity': int(line.split()[-2])})
                    if out['output_verbosity'] != 1:
                        out['warnings'].append(
                            'Parsing is only supported '
                            'directly supported if output verbosity is set to 1'
                        )

        # Parses some of the DOS parameters
        if 'DOS' in line:
            i += 1
            line = wann_out_file[i]
            while '-----' not in line:
                line = wann_out_file[i]
                if 'Minimum energy range for DOS plot' in line:
                    out.update({'dos_energy_min': float(line.split()[-2])})
                if 'Maximum energy range for DOS plot' in line:
                    out.update({'dos_energy_max': float(line.split()[-2])})
                if 'Energy step for DOS plot' in line:
                    out.update({'dos_energy_step': float(line.split()[-2])})
                if 'Grid size' in line:
                    line = line.split()[4:-1]
                    out.update({'dos_kmesh': 
                        [int(line[0]), int(line[2]), int(line[4])]}
                        )
                i += 1

        # if 'Properties calculated in module  d o s' in line:
        #     w90_conv = True

    return out


def dos_parser(dos_dat_path):
    """
    Parsers the dos output data, along with the special points retrieved
    from the input kpoints to construct a BandsData object which is then
    returned. Cannot handle discontinuities in the kpath, if two points are
    assigned to same spot only one will be passed.

    :param band_dat_path: file path to the aiida_band.dat file
    :param band_kpt_path: file path to the aiida_band.kpt file
    :param special_points: special points to add labels to the bands a dictionary in
        the form expected in the input as described in the wannier90 documentation
    :return: BandsData object constructed from the input params
    """
    import numpy as np
    from aiida.orm import XyData

    # imports the data
    # TODO support spin case
    out_dat = np.genfromtxt(dos_dat_path, usecols=(0, 1))

    dos = XyData()
    dos.set_x(out_dat[:, 0], 'energy', 'eV')
    dos.set_y(out_dat[:, 1], 'dos', 'states/eV')
    return dos
