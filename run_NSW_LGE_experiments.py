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
import glob
import json
from utils import read_ballots_stv, read_ballots_txt, read_ballots_json, read_ballots_blt, Candidate
from subprocess import run

from cProfile import Profile
from pstats import SortKey, Stats

ContestMetadata = namedtuple("ContestMetadata", ["votes", "vacancies", "candidates", "upper_bound"])

displaynames = {}

data_aus_big = []

data_rem = []

data_aus_small = [
    ("FedAus16/FederalSenate2016ACT.json", 2),
    ("FedAus16/FederalSenate2016NT.json", 2),
    ("FedAus19/FederalSenate2019ACT.json", 2),
    ("FedAus19/FederalSenate2019NT.json", 2),
    ("FedAus22/2022ACT.json", 2),
    ("FedAus22/2022NT.json", 2)
]

datafiles = []

ubs = {}


def run_audit(metadata):
    reps = 1
    counter = 0  # 1-5148

    # -3 == new without new ub
    # -1 == baseline without new ub, aka Baseline
    # 0 == baseline (with new ub), aka Baseline+U
    # 3 == new, aka New+Both
    # 4 == new without lse, aka New+DLB
    # 5 == new without dlb, aka New+LSE
    # 6 == new without dlb and lse, aka New
    # versions = [4, 5, 6, 0, 3, -1, -3]
    #versions = [4, 5, 6, 0, 3, -1]
    # just running version 0.
    #versions=[0]
    #print(
    #    "datafile, candidates, seats, quota, init_ub, found_lb, found_ub, nodes_exp, minlps_solved, solve(s), time(s), lse, dlb, eqlb, new_ub")
    #for version in versions:
    #   for (datafile, seats) in data_rem:
    #        if "example" in datafile:
    #            path = "./data/" + datafile
    directory = "../stvdata/"
    for datafile in os.listdir(directory):
        # Ignore the files that aren't stv files.
        if not datafile.endswith(".stv"):
            continue
        path = "../stvdata/" + datafile

        displayname = datafile.split(".")[0]
        contest_data = metadata[displayname]

        args = ['-d', path, '-log', f"log_{datafile.replace('/', '')}_{0}.log", '-s', str(contest_data.vacancies),
                        '-pc', '30', '-g', '0.01', '-agap', '0', '-limit', '10800', '-displayname', displayname, '-m']
        #args += ['-ub', str(ubs[displayname])]
        args += ['-ub', str(contest_data.upper_bound)]

        for _ in range(reps):
                counter += 1
                # print(version, datafile, counter); continue
                #if counter != int(os.environ['SLURM_ARRAY_TASK_ID']): continue
                #print(" ".join(sys.argv))
                # with Profile() as profile:
                # print(displayname)
                command = [sys.executable, "pymarginstv.py"] + args
                run(command)
                #exec(open("pymarginstv.py").read())
                    # (
                    #     Stats(profile)
                    #     .strip_dirs()
                    #     .sort_stats(SortKey.TIME)
                    #     .print_stats()
                    # )


def run_ub():
    """
    Requires https://github.com/AndrewConway/ConcreteSTV installed in `../ConcreteSTV/target/debug`
    """
    for (datafile, _) in datafiles:
        if "example" in datafile:
            path = "./data/" + datafile
        else:
            path = "../stvdata/" + datafile
        if path.endswith(".txt"):
            path = path.split(".txt")[0] + ".blt"
        if path.endswith(".blt"):
            path = path.split(".blt")[0] + ".json"
        if path.endswith(".json"):
            outfile = path.split(".json")[0] + ".vchange"
            print(f'{path} 1st:')
            os.system(f'../ConcreteSTV/target/debug/change_outcomes beSTV "{path}" -o "{outfile}"')
        else:
            print("path does not end with .txt, .blt, or .json")

def read_upper_bound_csv():
    upper_bounds = pd.read_csv("stvdata/summary_NSW2021Changes_BESTV_BetterBounds.csv")

    contest_metadata = {}
    for index, row in upper_bounds.iterrows():
        print(row["Electorate"], row["Votes"], row["Vacancies"], row["Candidates"], row["Min Manipulation"])
        contest_metadata[row["Electorate"]] = ContestMetadata(Votes=row["Votes"], Vacancies=row["Vacancies"], Candidates=row["Candidates"], UpperBound=row["Min Manipulation"])

    return contest_metadata

def get_ub_csv():
    print("datafile, ub")
    for (datafile, _) in datafiles:
        if "example" in datafile:
            path = "./data/" + datafile
        else:
            path = "../stvdata/" + datafile
        if path.endswith(".txt"):
            path = path.split(".txt")[0] + ".json"
        if path.endswith(".blt"):
            path = path.split(".blt")[0] + ".json"
        if path.endswith(".json"):
            infile = path.split(".json")[0] + "FP21.vchange"
            with open(infile) as file:
                res = json.load(file)
                min_ub = min([change["ballots"]["n"] for change in res["changes"]])
                print(f'{displaynames[datafile]}, {min_ub}')


def save_ub_changes_to_json():
    for (datafile, _) in datafiles:
        if "example" in datafile:
            path = "./data/" + datafile
        else:
            path = "../stvdata/" + datafile
        if path.endswith(".blt"):
            path = path.split(".blt")[0] + ".json"
        if path.endswith(".json"):
            infile = path.split(".json")[0] + ".vchange"
            if "Aberdeenshire-ward-8-mid-formartine" not in displaynames[datafile]:
                continue
            # print(displaynames[datafile])
            with open(infile) as file:
                res = json.load(file)
                min_ub = min([change["ballots"]["n"] for change in res["changes"]])
                print(f'{displaynames[datafile]}, {min_ub}')
                changeset = res["changes"][0]
                orig = res["original"]
                for change in changeset["ballots"]["changes"]:
                    candto = change["candidate_to"]
                    candfrom = change["from"]["candidate"]
                    def f(i):
                        if i == candfrom: return candto
                        if i == candto: return candfrom
                        return i
                    for ballot in change["from"]["ballots"]:
                        from_n = ballot["n"]
                        # if ballot["from"] < len(orig["atl"]):
                        #     pass
                        #     # TODO
                        orig_n = orig["btl"][ballot["from"]]["n"]
                        if from_n != orig_n:
                            orig["btl"].append({"n": from_n, "candidates": [f(i) for i in orig["btl"][ballot["from"]]["candidates"]]})
                            orig["btl"][ballot["from"]]["n"] -= from_n
                        else:
                            orig["btl"][ballot["from"]]["candidates"] = [f(i) for i in orig["btl"][ballot["from"]]["candidates"]]
                            # print(orig["btl"][ballot["from"]]["candidates"])
                # for change in res["changes"]:
                #     print(change["ballots"]["n"], change["ballots"]["n"] - min_ub)
                # with open(path) as file2:
                #     res2 = json.load(file2)
                #     pass
                with open('data/data_election_temp_example.json', 'w') as f:
                    json.dump(orig, f)


def txt_to_blt():
    for (datafile, seats) in datafiles:
        if "example" in datafile:
            path = "./data/" + datafile
        else:
            path = "../stvdata/" + datafile
        if path.endswith(".txt"):
            dest = path.split(".txt")[0] + ".blt"
            output = ""
            with open(path) as file:
                cands = file.readline().split(",")
                assert cands[-1] != "", "error"
                numcands = len(cands)
                if int(cands[0]) == 0:
                    offset = 1
                else:
                    offset = 0
                output += f"{numcands} {seats}\n"
                names = file.readline().split(",")
                names[-1] = names[-1][:-1]
                parties = file.readline().split(",")
                parties[-1] = parties[-1][:-1]
                # print(names, parties)
                file.readline()
                file.readline()
                for line in file.readlines():
                    row = line.split(" : ")
                    order = row[0][:-1][1:].split(",")
                    count = int(row[1])
                    output += f"{count} {' '.join([str(int(i) + offset) for i in order])} 0\n"
                output += "0\n"
                for i in range(numcands):
                    names[i] = names[i].replace('\"', '')
                    parties[i] = parties[i].replace('\"', '')
                    output += f'"{names[i]}" "{parties[i]}"\n'
                output += f'"{displaynames[datafile]}"\n'
                # print(output)
                with open(dest, 'w') as file:
                    file.write(output)

def simulate():
        for (datafile, seats) in datafiles:
            if "example" in datafile:
                path = "./data/" + datafile
            else:
                path = "../stvdata/" + datafile
            displayname = displaynames[datafile]

            # candidates = [0]
            # seats = 0
            # if path.endswith(".blt"):
            #     candidates, ballots, _, cid2num, totvotes, seats = read_ballots_blt(path)
            # print(f"{displayname}, {len(candidates)}, {seats}, {counter}"); continue
            print("---------")
            print(displayname)
            print("---------")
            args = ['-d', path, '-log', f"log_{datafile.replace('/', '')}_justsimSR.log", '-s', str(seats),
                        '-just_sim', '-senate_rules', '-displayname', displayname, '-m']
            command = [sys.executable, "pymarginstv.py"] + args
            run(command)
            args = ['-d', path, '-log', f"log_{datafile.replace('/', '')}_justsim.log", '-s', str(seats),
                        '-just_sim', '-displayname', displayname, '-m']
            command = [sys.executable, "pymarginstv.py"] + args
            run(command)

            # compare
            print("---------")
            with open(f"log_{datafile.replace('/', '')}_justsimSR.log", "r") as file:
                lines = file.readlines()
                lastTwo1 = lines[len(lines)-2:-1]
                with open(f"log_{datafile.replace('/', '')}_justsim.log", "r") as file:
                    lines2 = file.readlines()
                    lastTwo2 = lines2[len(lines2)-2:-1]
                    if lastTwo1 != lastTwo2:
                        print("{displayname} difference in outcome")
            result = run(["diff", f"log_{datafile.replace('/', '')}_justsimSR.log", f"log_{datafile.replace('/', '')}_justsim.log"],\
                    capture_output=True, text=True)
            print(result.stdout)

if __name__ == "__main__":
    bounds = read_upper_bound_csv()
    run_audit(bounds)
    #txt_to_blt()
    #run_ub()
    #get_ub_csv()
    # save_ub_changes_to_json()
    #simulate()
