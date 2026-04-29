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
import pandas as pd
from collections import namedtuple
from subprocess import run

ContestMetadata = namedtuple("ContestMetadata", ["votes", "vacancies", "candidates", "upper_bound"])
data_directory = "../stvdata/"

def run_audit(metadata):
    reps = 1
    counter = 0  # 1-5148

    # version
    # 0 == baseline (with new ub), aka Baseline+U
    directory = data_directory + "nswLGE/"
    for datafile in os.listdir(directory):
        # Ignore the files that aren't stv files.
        if not datafile.endswith(".stv"):
            continue

        path = directory + datafile
        displayname = datafile.split(".")[0]
        contest_data = metadata[displayname]

        args = ['-d', path, '-log', f"log_{datafile.replace('/', '')}_{0}.log", '-s', str(contest_data.vacancies),
                        '-pc', '30', '-g', '0.01', '-agap', '0', '-limit', '10800', '-displayname', displayname, '-m',
                        '-ub', str(int(contest_data.upper_bound))]

        for _ in range(reps):
                counter += 1
                command = [sys.executable, "pymarginstv.py"] + args
                run(command)

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
