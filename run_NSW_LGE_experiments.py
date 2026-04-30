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
It assumes an upper-bound csv file called `/summary_NSW2021Changes_BESTV_BetterBounds.csv` in `../stvdata/`
 with columns "Electorate,Votes,Vacancies,Candidates,Min Manipulation", matching
the format produced by `nsw_beSTV_changes.rs`.
"""

import sys
import os
from asyncio import as_completed

import pandas as pd
from collections import namedtuple
from subprocess import run
from concurrent.futures import ThreadPoolExecutor

ContestMetadata = namedtuple("ContestMetadata", ["votes", "vacancies", "candidates", "upper_bound"])
data_directory = "stvdata/"
TIMEOUT = 2000
THREADS = 16
# Skip data files if a log file is already present. Note this does *not* guarantee that the run completed successfully -
# just that it started.
SKIP_DONE = True

def run_audit(metadata):
    # version
    # 0 == baseline (with new ub), aka Baseline+U

    directory = data_directory + "nswLGE/"
    futures = {}

    # done logs look like log_LGENAME.stv_0.log
    done_logs = list(filter(lambda l: l.endswith(".log"), os.listdir(".")))
    done_log_names = set(map(lambda x: x.split(".")[0].split("_")[1], done_logs))

    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        for datafile in os.listdir(directory):

            # Ignore the files that aren't stv files, or that have already been done if the SKIP_DONE flag is true..
            # The LGENAME must match exactly, because quite a few are substrings of others
            if not datafile.endswith(".stv") or (SKIP_DONE and datafile.split(".")[0] in done_log_names):
                continue

            path = directory + datafile
            displayname = datafile.split(".")[0]
            contest_data = metadata[displayname]

            args = ['-d', path, '-log', f"log_{datafile.replace('/', '')}_{0}.log", '-s', str(contest_data.vacancies),
                    '-pc', '30', '-g', '0.01', '-agap', '0', '-limit', '10800', '-displayname', displayname, '-m']

            # Add upper bound from file if present.
            if pd.notna(contest_data.upper_bound):
                args += ['-ub', str(int(contest_data.upper_bound))]

            # command = [sys.executable, "pymarginstv.py"] + args
            future = executor.submit(run_pymarginstv, args)
            print(f"Starting LGA: {displayname}")
            futures[future] = displayname

        for future in as_completed(futures):
            displayname = futures[future]
            try:
                result = future.result()
                print(f"Success: {displayname}; {result}")
            except Exception as e:
                print(f"Failure: {displayname}")
            finally:
                del futures[future]


def run_pymarginstv(args):
    return run([sys.executable, "pymarginstv.py"] + args, check=True, capture_output=True, text=True, timeout=TIMEOUT)

def read_upper_bound_csv():
    upper_bounds = pd.read_csv(data_directory + "summary_NSW2021Changes_BESTV_BetterBounds.csv")

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
