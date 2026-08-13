#
#    Copyright (C) 2025  Michelle Blom, Alexander Ek, Vanessa Teague
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
This script is used to compare the results of margin calculation upper bounds (which can be taken from
concreteSTV, or anywhere else) with the lower-bound calculationso of pymarginstv.
It assumes that the ballot files are in `../stvdata/nswLGE`,
It assumes an upper-bound csv file called `/summary_NSW2021Changes_BESTV_BetterBounds.csv` in `test/data`
 with columns "Electorate,Votes,Vacancies,Candidates,Min Manipulation", matching
the format produced by `nsw_beSTV_changes.rs`.
"""

import sys
import os

import pandas as pd
from collections import namedtuple
from subprocess import run

ContestMetadata = namedtuple("ContestMetadata", ["votes", "vacancies", "candidates", "upper_bound"])
NSW_DATA_DIRECTORY = "../stvdata/nswLGE/"
STV_UBS = "test/data/summary_NSW2021Changes_BESTV_BetterBounds.csv"
TIMEOUT = '10800'
THREADS = '30'
# Skip data files if a log file is already present. Note this does *not* guarantee that the run completed successfully -
# just that it started.
SKIP_DONE = True
# Skip the mayoral contests, which are actually IRV, i.e. single winner, and therefore uninteresting because
# auditable by RAIRE.
SKIP_MAYORAL = True


def run_audit(metadata):
    # version
    # 0 == baseline (with new ub), aka Baseline+U

    # done logs look like log_LGENAME.stv_0.log
    done_logs = list(filter(lambda l: l.endswith(".log"), os.listdir(".")))
    done_log_names = set(map(lambda x: x.split(".")[0].split("_")[1], done_logs))

    for datafile in os.listdir(NSW_DATA_DIRECTORY):

        # Ignore the files that aren't stv files, or that have already been done if the SKIP_DONE flag is true.
        # The LGENAME must match exactly, because quite a few are substrings of others.
        # Ignore Mayoral contests if requested.
        if (not datafile.endswith(".stv") or
                (SKIP_DONE and datafile.split(".")[0] in done_log_names) or
                (SKIP_MAYORAL and "Mayoral" in datafile.split(".")[0])):
            continue

        path = NSW_DATA_DIRECTORY + datafile
        displayname = datafile.split(".")[0]
        contest_data = metadata[displayname]

        args = ['-d', path, '-log', f"log_{datafile.replace('/', '')}_{3}.log", '-s', str(contest_data.vacancies),
                '-pc', THREADS, '-g', '0.01', '-agap', '0', '-limit', TIMEOUT, '-displayname', displayname, '-m',
               '-lse', '-eqlb', '-dlb']

        # Add upper bound from file if present.
        if pd.notna(contest_data.upper_bound):
            args += ['-ub', str(int(contest_data.upper_bound))]

        print(f"Starting LGA: {displayname}")


        try:
            command = [sys.executable, "pymarginstv.py"] + args
            run(command)
            print(f"Success: {displayname}.")
        except Exception as e:
            print(f"Failure: {displayname}. Error: {e}")


def read_upper_bound_csv():
    upper_bounds = pd.read_csv(STV_UBS)

    contest_metadata = {}
    for index, row in upper_bounds.iterrows():
        #print(row["Electorate"], row["Votes"], row["Vacancies"], row["Candidates"], row["Min Manipulation"])
        contest_metadata[row["Electorate"]] = ContestMetadata(votes=row["Votes"], vacancies=row["Vacancies"], candidates=row["Candidates"], upper_bound=row["Min Manipulation"])

    return contest_metadata

if __name__ == "__main__":
    bounds = read_upper_bound_csv()
    run_audit(bounds)
    #txt_to_blt()
    #run_ub()
    #get_ub_csv()
    # save_ub_changes_to_json()
    #simulate()
