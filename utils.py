#
#    Copyright (C) 2023  Michelle Blom
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


from __future__ import annotations

import numpy as np
import math
import json

from typing import Iterable, Optional, Protocol, TextIO


class CandidateLike(Protocol):
    """
        Structural type for candidate records: the full Candidate class
        below, or any lightweight stand-in (e.g. stvtree.CandLite) that
        exposes a candidate number and first-preference tally.
    """
    @property
    def num(self) -> int: ...

    @property
    def fp_votes(self) -> float: ...


class Ballot:
    """
        Data structure representing both a ballot type--a ranking over
        candidates--and the number of votes that exist of that type, and
        an equivalence class. In this codebase, we do not use the ATL
        indicator for the ballot (ie., whether it is an above the line or
        below the line ballot). The field is there as it is used in 
        other codebases where this code has been drawn from, and the 
        methods for reading in STV data make use of the field.

        Note: sometimes this data structure is used to represent a single
        ballot, or a collection of ballots cast with the same ranking.
    """
    def __init__(self, num: int, votes: float, prefs: list[int], \
        totcand: int, atl: bool = False) -> None:
        self.num = num # Numeric identifier for ballot

        # Total votes expressed on the papers of this ballot type/ballot
        self.votes = votes

        # Ranking over candidates
        self.prefs = prefs

        # Is this an above the line ballot/below the line
        self.atl = atl

        # Number of papers cast of this ballot type.
        self.papers = votes

        # Indexes of each candidate
        self.ranks: list[int] = [-1]*totcand

        for i in range(len(prefs)):
            self.ranks[prefs[i]] = i

    def __str__(self) -> str:
        """
            Convert ballot to a string representation.
        """
        desc = "Ballot {} Ranking ".format(self.num)

        for p in self.prefs:
            desc += str(p) + ", "

        desc += "Votes {}, Papers {}".format(self.votes, self.papers)

        return desc


class Candidate:
    """
        Data structure representing a candidate. Candidate's have a 
        numeric id (how they are referred to in the ballot files) and
        a number (index) representing their position in a candidate
        list. Group id/position/ATL/BTL/mentions are not used in this
        codebase. 
    """
    def __init__(self, num: int, idn: int) -> None:
        self.num = num
        self.id = idn
        self.name: Optional[str] = None
        self.group_id: Optional[int] = None
        self.position: Optional[int] = None

        self.num_atls = 0
        self.num_btls = 0

        # Ids of ballots whose first preference is this candidate.
        self.ballots: list[int] = []
        self.fp_votes: float = 0

        # For simulation purposes
        self.sim_votes: float = 0
        self.bweights: list[tuple[int, float]] = []
        self.standing = 1
        self.seat = -1
        self.surplus: float = 0

class Group:
    def __init__(self, idstr: int) -> None:
        self.id = idstr
        self.cands: list[int] = []


def read_ballots_blt(path: str) -> tuple[list[Candidate], list[Ballot], \
    dict[int, Group], dict[int, int], int, int]:
    ballots: list[Ballot] = []
    candidates: list[Candidate] = []
    cid2num: dict[int, int] = {}

    total_votes = 0

    with open(path, "r") as cvr:
        lines = [l.strip() for l in cvr.readlines() if l.strip() != ""]

        cands,seats = [int(tok) for tok in lines[0].split()]

        split_idx = lines.index("0")

        ballot_strs = lines[1:split_idx]
        cand_strs = lines[split_idx+1:split_idx+1+cands]

        for i in range(len(cand_strs)):
            cand = Candidate(i, i+1)
            cand.name = cand_strs[i]
            cand.group_id = -1
            cand.position = -1

            candidates.append(cand)
            cid2num[cand.id] = i


        bcntr = 0

        ncands = len(candidates)

        for bline in ballot_strs:
            toks = [int(t) for t in bline.split()]

            n = toks[0]
            prefs = [cid2num[p] for p in toks[1:-1]]

            ballot = Ballot(bcntr, n, prefs, ncands)
            ballots.append(ballot)

            fpcand = candidates[prefs[0]]
            fpcand.ballots.append(bcntr)
            fpcand.fp_votes += n

            total_votes += n

            bcntr += 1

    return candidates,ballots,{},cid2num,total_votes,seats


def read_ballots_txt(path: str) -> tuple[list[Candidate], list[Ballot], \
    dict[int, Group], dict[int, int], int]:
    ballots: list[Ballot] = []
    candidates: list[Candidate] = []
    cid2num: dict[int, int] = {}

    total_votes = 0
    us_ver = True if path.endswith(".us") else False

    with open(path, "r") as cvr:
        lines = cvr.readlines()

        clist = [int(c.strip()) for c in lines[0].strip().split(',')]
        ncands = len(clist)

        for i in range(len(clist)):
            cand = Candidate(i, clist[i])
            cand.name = str(clist[i])
            cand.group_id = -1
            cand.position = -1

            candidates.append(cand)
            cid2num[clist[i]] = i


        bcntr = 0
        nextline = 2 if us_ver else 5

        for i in range(nextline, len(lines)):
            line = lines[i].strip()
            toks = [t.strip() for t in line.split(':')]

            pre_prefs = toks[0][1:-1].split(',') 

            prefs = [int(p.strip()) for p in pre_prefs if p != '']

            if prefs == []:
                continue

            votes = int(toks[1])

            cprefs = [cid2num[p] for p in prefs]

            if len(candidates) in cprefs:
                print("Invalid canidate number in preferences")

            ballot = Ballot(bcntr, votes, cprefs, ncands, atl=False)
            ballots.append(ballot)

            fpcand = candidates[cprefs[0]]
            fpcand.ballots.append(bcntr)
            fpcand.fp_votes += votes

            total_votes += votes

            bcntr += 1

    return candidates,ballots,{},cid2num,total_votes

def read_ballots_json(path: str) -> tuple[list[Candidate], list[Ballot], \
    dict[int, Group], dict[int, int], int]:
    ballots: list[Ballot] = []
    candidates: list[Candidate] = []
    id2group: dict[int, Group] = {}
    cid2num: dict[int, int] = {}

    total_votes = 0

    with open(path, "r") as cvr:
        data = json.load(cvr)

        # get candidates
        cid = 0
        for cand in data["metadata"]["candidates"]:
            name = cand["name"]
            try:
                party = int(cand["party"])
            except KeyError:
                party = -1
            try:
                pos = int(cand["position"])
            except KeyError:
                pos = -1

            cobj = Candidate(cid, cid)
            cobj.name = name
            cobj.group_id = party
            cobj.position = pos

            candidates.append(cobj)

            # Candidate id to number mapping not needed for this
            # file type, but required for consistency across file
            # types
            cid2num[cid] = cid
            cid += 1


        ncands = len(candidates)

        # get party info
        pid = 0
        try:
            for party in data["metadata"]["parties"]:
                group = Group(pid)

                for num in party["candidates"]:
                    group.cands.append(num)

                id2group[pid] = group

                pid += 1
        except KeyError:
            print("No parties or bad data in party lists for candidates.")

        # process atl ballots
        bcntr = 0
        try:
            for atl in data["atl"]:
                n = int(atl["n"])

                groups = [id2group[int(g)] for g in atl["parties"]]

                prefs = []
                for g in groups:
                    prefs.extend(g.cands)
                
                blt = Ballot(bcntr, n, prefs, ncands, atl=True)

                fcand = candidates[prefs[0]]
                fcand.ballots.append(bcntr)
                fcand.fp_votes += n

                fcand.num_atls += n

                total_votes += n

                ballots.append(blt)
                bcntr += 1
        except KeyError:
            print("No ATL votes or bad data listing ATL parties.")

        # process btl ballots
        try:
            for btl in data["btl"]:
                n = int(btl["n"])

                # no need to use cid2num since candidate ids range from 0 to
                # num_cands -1 already.
                prefs = [int(c) for c in btl["candidates"]]

                blt = Ballot(bcntr, n, prefs, ncands, atl=False)

                fcand = candidates[prefs[0]]
                fcand.ballots.append(bcntr)
                fcand.fp_votes += n

                fcand.num_btls += n

                total_votes += n
                ballots.append(blt)

                bcntr += 1
        except KeyError:
            print("No BTL votes or bad data listing BTL candidates.")
    
    return candidates,ballots,id2group,cid2num,total_votes
            

def compute_simple_ub(candidates: list[Candidate], quota: int, \
    winners: list[int]) -> float:
    sub = np.inf

    for c in candidates:
        if not c.num in winners:
            sub = min(sub, quota - c.fp_votes)

    return sub

def compute_weub(candidates: list[Candidate], winners: list[int], \
    order_c: list[int], order_a: list[int], \
    tallies: dict[int, list[float]]) -> float:
    seated = set(winners)
    standing = set([c.num for c in candidates]) 

    weub = np.inf
    for r in range(len(order_c)):
        cnum = order_c[r]
        standing.remove(cnum)

        if not seated:
            break

        if order_a[r] == 1:
            seated.remove(cnum)
        else:
            # tally of candidate eliminated in this round
            ctally = tallies[cnum][r] 

            for w in seated:
                wtally = tallies[w][r]

                change = math.ceil(wtally-ctally)

                weub = min(weub, change)

                halfless = wtally-0.5*change

                use_half = True
                for s in standing:
                    if s == w or s == cnum:
                        continue

                    if tallies[s][r] < halfless:
                        use_half = False
                        break

                if use_half:
                    weub = min(weub, math.ceil(0.5*change))

    return weub
                       


def simulate_stv(ballots: list[Ballot], candidates: list[Candidate], \
    nseats: int, order_c: list[int], order_a: list[int], \
    winners: list[int], log: Optional[TextIO] = None) -> tuple[int, dict[int, list[float]], float]:

    ncand = len(candidates)
    cand_tallies_by_round: dict[int, list[float]] = \
        { cand.num : [0]*ncand for cand in candidates }

    totvotes: float = 0
    if log != None:
        print("First preference tallies: ", file=log, flush=True)

    for cand in candidates:
        cand.sim_votes = 0
        cand.bweights = []
        cand.standing = 1
        cand.seat = -1
        cand.surplus = -1

        for bid in cand.ballots:
            cand.bweights.append((bid, 1))
            cand.sim_votes += ballots[bid].votes

        cand_tallies_by_round[cand.num][0] = cand.sim_votes

        totvotes += cand.sim_votes

        if log != None:
            print(f"    Candidate {cand.id} {cand.sim_votes}",file=log,\
                flush=True)

    # Step 1: Determine quota
    quota = (int)(1.0 + (totvotes/(nseats+1.0))) 

    if log != None:
        print(f"The quota for election is {quota}", file=log, flush=True)

    surpluses: list[Candidate] = []

    currseat = 0

    r = -1

    while currseat < nseats:
        standing = 0

        # if a candidate has a quota, add them to the list of 
        # candidates with a surplus
        for cand in candidates:
            if cand.standing:
                standing += 1

            if cand.surplus != -1 or not cand.standing:
                continue

            if cand.standing and cand.sim_votes >= quota:
                cand.surplus = max(0, cand.sim_votes - quota)
                insert_surplus(surpluses, cand)

                #order_q[cand.num] = r

        if standing == 0:
            break

        r = max(0, r)

        if standing == nseats - currseat:
            surpluses = []
            if log != None:
                print("Number of candidates left standing equals number of "\
                    "remaining seats", file=log, flush=True)

            slist: list[int] = []
            for cand in candidates:
                if cand.standing:
                    inserted = False
                    for i in range(len(slist)):
                        if cand.sim_votes > candidates[slist[i]].sim_votes:
                            slist.insert(i, cand.num)
                            inserted = True
                            break

                    if not inserted:
                        slist.append(cand.num)

            for cnum in slist:
                cand = candidates[cnum]

                if log != None:
                    print("Candidate {}, {}, elected (votes {})".format(\
                        cand.id, cand.name, cand.sim_votes), file=log, flush=True)

                cand.seat = currseat
                currseat += 1

                cand.standing = 0
                order_c.append(cnum)
                order_a.append(1)

                winners.append(cand.num)

        if surpluses == []:
            # Eliminated candidate with fewest votes.
            # Distribute votes at their current value.
            leastvotes: float = -1
            toeliminate: Optional[Candidate] = None

            for cand in candidates:
                if cand.standing:
                    if log != None:
                        print("Candidate {}, {}, has {} votes".format(cand.id, cand.name,\
                            cand.sim_votes), file=log, flush=True)

                    if leastvotes == -1 or cand.sim_votes < leastvotes:
                        leastvotes = cand.sim_votes
                        toeliminate = cand


            if toeliminate is not None:
                order_c.append(toeliminate.num)
                order_a.append(0)

                if log != None:
                    print("Candidate {}, {}, eliminated on {} votes".format(\
                        toeliminate.id, toeliminate.name, toeliminate.sim_votes), file=log,\
                        flush=True)

                eliminate_candidate(toeliminate, candidates, ballots, log)

                for cand in candidates:
                    if cand.surplus != -1 or not cand.standing:
                        continue

                    if log != None:
                        print("Candidate {}, {}, has {} votes".format(cand.id, cand.name,\
                            cand.sim_votes), file=log, flush=True)

                    if cand.standing and cand.sim_votes >= quota:
                        cand.surplus = max(0, cand.sim_votes - quota)
                        surpluses.append(cand)

                        #order_q[cand.num] = r

                        if log != None:
                            print(f"Candidate {cand.id}, {cand.name}, has a quota.", \
                                file=log, flush=True) 

            if r != ncand-1:
                for cand in candidates:
                    if cand.standing:
                        cand_tallies_by_round[cand.num][r+1] = cand.sim_votes
            r += 1

        else:
            new_surpluses: list[Candidate] = []

            while surpluses != []:
                # Start with candidate with the largest surplus
                elect = surpluses.pop(0)

                elect.seat = currseat
                currseat += 1

                order_c.append(elect.num)
                order_a.append(1)

                winners.append(elect.num)

                if log != None:
                    print("Candidate {}, {}, elected (votes {})".format(elect.id, elect.name,\
                        elect.sim_votes), file=log, flush=True)

                elect.standing = 0
                if currseat < nseats:
                    # Distribute surplus
                    distribute_surplus(elect, candidates, ballots, log)

                next_surpluses: list[Candidate] = []
                for cand in candidates:
                    if cand.surplus != -1 or not cand.standing:
                        continue

                    if cand.sim_votes >= quota:
                        cand.surplus = max(0, cand.sim_votes - quota)
                        insert_surplus(next_surpluses, cand)
                        #order_q[cand.num] = r

                new_surpluses.extend(next_surpluses)
            
                if r != ncand-1:
                    for cand in candidates:
                        if cand.standing:
                            cand_tallies_by_round[cand.num][r+1]=cand.sim_votes
                r += 1

            surpluses = new_surpluses

        if currseat == nseats:
            # All seats filled.
            if len(order_c) != len(candidates):
                for cand in candidates:
                    if cand.standing:
                        order_c.append(cand.num)
                        order_a.append(0)

            break

    return quota, cand_tallies_by_round, totvotes

def next_candidate(prefs: list[int], cnum: int, \
    candidates: list[Candidate]) -> int:
    idx = prefs.index(cnum)

    for p in prefs[idx+1:]:
        cand = candidates[p]
        if not cand.standing or cand.surplus != -1:
            continue

        return p

    return -1 


def insert_surplus(surpluses: list[Candidate], cand: Candidate) -> None:
    for i in range(len(surpluses)):
        if cand.surplus >= surpluses[i].surplus:
            surpluses.insert(i, cand)
            return

    surpluses.append(cand)


def distribute_surplus(elect: Candidate, candidates: list[Candidate], \
    ballots: list[Ballot], log: Optional[TextIO]) -> None:
    elect.standing = 0

    if elect.surplus < 0.001: return

    tvalue = elect.surplus/elect.sim_votes

    if log != None:
        print("Transfer value is {}".format(tvalue), file=log)

    # Each ballot in elect's tally now has value of 'tvalue'
    totransfer: list[list[tuple[int, float]]] = [[] for c in candidates]

    for bid,w in elect.bweights:
        blt = ballots[bid]

        nextc = next_candidate(blt.prefs, elect.num, candidates)

        if nextc != -1:
            totransfer[nextc].append((bid, tvalue*w))

    for cand in candidates:
        tlist = totransfer[cand.num]

        total: float = 0
        for bid,weight in tlist:
            blt = ballots[bid]

            cand.ballots.append(bid)
            cand.sim_votes += weight*blt.votes

            total += weight*blt.votes

            cand.bweights.append((bid,weight))

        if log != None:
            print("{} votes distributed from {} to {}".format(\
                total, elect.name, cand.name), file=log)

    elect.sim_votes -= elect.surplus
    elect.surplus = -1


def eliminate_candidate(toelim: Candidate, candidates: list[Candidate], \
    ballots: list[Ballot], log: Optional[TextIO]) -> None:
    toelim.standing = 0

    totransfer: list[list[tuple[int, float]]] = [[] for c in candidates]

    # Distribute all ballots (at their current value) to rem candidates
    for bid,weight in toelim.bweights:
        nextc = next_candidate(ballots[bid].prefs, toelim.num, candidates)

        if nextc != -1:
            totransfer[nextc].append((bid, weight))

    toelim.sim_votes = 0

    for cand in candidates:
        tlist = totransfer[cand.num]

        total: float = 0
        for bid,weight in tlist:
            blt = ballots[bid]

            cand.ballots.append(bid)
            cand.sim_votes += weight*blt.votes

            total += weight*blt.votes

            cand.bweights.append((bid,weight))

        if total > 0:
            if log != None:
                print("{} votes distributed from {} to {}".format(\
                    total, toelim.name, cand.name), file=log, flush=True)


def next_mod(mask: list[int], n: int) -> int:
    i = 0
    while i < n and mask[i]:
        mask[i] = 0
        i += 1

    if i < n:
        mask[i] = 1
        return 1
	
    return 0


def CreateEquivalenceClasses(order_c: list[int], totcand: int) \
    -> tuple[list[Ballot], int, dict[tuple[int, ...], int]]:
    ncand = len(order_c)
    mask = [0]*ncand

    cmap: dict[tuple[int, ...], int] = {}

    cntr = 0
    classes: list[Ballot] = []

    while next_mod(mask, ncand):
        j = -1
        for i in range(ncand):
            if mask[i]:
                j = i
                break
				
        if j < 0: 
            continue
	
        prefs = []
        prefs.append(order_c[j]);

        for i in range(j+1, ncand): 
            if mask[i]:
                prefs.append(order_c[i])

        classes.append(Ballot(cntr, 0, prefs, totcand))

        cmap[tuple(prefs)] = cntr;
        
        cntr += 1
        

    return classes,cntr,cmap

 
# Create equivalence classes when we have only a partial order (prefix)
# Note that total number of possible ballot types (assuming smallest number 
# of possible rankings is 1) with n candidates:
# \sum_{i = 1}^{n} n! / (n-i)!
def gen_equivalence_classes(order_c: list[int], remainder: list[int], \
    totcand: int) -> tuple[list[Ballot], int, dict[tuple[int, ...], int]]:
    first,cntr,cmap = CreateEquivalenceClasses(order_c, totcand)

    second = []
    for r in remainder:
        second.append(Ballot(cntr, 0, [r], totcand))
        cmap[(r,)] = cntr
        cntr += 1
        for f in first:
            newc = f.prefs + [r]
            second.append(Ballot(cntr, 0, newc, totcand))
            cmap[tuple(newc)] = cntr
            cntr += 1

    return first + second, cntr, cmap



def reduce_ballots(ncands: int, order_c: list[int], remainder: list[int], \
    merge_map: dict[int, int], ballots: list[Ballot], \
    rballots: list[Ballot], classmap: dict[tuple[int, ...], int]) -> None:

    candpos = [0]*ncands

    i = 0
    for c in order_c:
        candpos[c] = i
        i += 1

    for b in ballots:
        new_prefs = []

        np = merge_map[b.prefs[0]]
        if np in remainder:
            new_prefs = [np]
        else:            
            new_prefs = [np]
            i = candpos[np]

            for p in b.prefs[1:]:
                np = merge_map[p]
                if np in new_prefs:
                    continue

                if np in remainder:
                    new_prefs.append(np)
                    break

                j = candpos[np]

                if j < i:
                    continue

                i = j
                new_prefs.append(np)
            
        # Get corresponding ballots from rballots
        rcntr = classmap[tuple(new_prefs)]
        rbal = rballots[rcntr]

        # Add to vote/paper tally.
        rbal.votes += b.votes
        rbal.papers += b.papers


def add_elim_sequence(elim_seq: list[int], m_order_c: list[int], \
    m_order_a: list[int], merge_map: dict[int, int], \
    segments: list[list[int]], supers: list[int], \
    merge_all: bool = True) -> None:

    """
        elim_seq    -  A sequence of consecutively eliminated candidates.
                       If the list is of sufficient length (> 3).
                       Candidates in elim_seq will be added to merge_map, with 
                       their mapped value being their id in the merged 
                       election outcome. If the list of not of sufficient
                       length, the candidate(s) will remain as themselves --
                       unmerged in the new outcome representation.

        m_order_c   -  Sequence of the candidates who are eliminated/elected
                       in each round of tabulation, listed in the order that
                       they are eliminated/elected. Represents the election
                       outcome with merged candidates.

        m_order_a   -  Sequence of events that occur in each round of 
                       tabulation (0 for elimination, 1 for election).
                       Represents the election outcome with merged candidates.

        merge_map   -  Map between original candidate ids and their potentially
                       new ids in the merged election representation.

        segments    -  A partition of the non-merged election outcome prefix
                       eg. [[1],[2,3,4],[5]] means that candidates 1 and 5
                       remain as 1 and 4 in the merged representation, but
                       candidates 2-4 are merged.

        supers      -  Ids of the super candidates.
    """ 
    le = len(elim_seq)
    if merge_all and le > 1:
        mc = elim_seq[0]
        m_order_c.append(mc)
        m_order_a.append(0)

        segments.append(elim_seq[:])
        supers.append(mc)

        for e in elim_seq:
            merge_map[e] = mc
  
    elif le < 3: 
        # Do not merge the candidates, add them to m_order_c, and m_order_a
        # as themselves. 
        
        for e in elim_seq:
            m_order_c.append(e)
            m_order_a.append(0)
            merge_map[e] = e
            segments.append([e])
    else:
        mc = elim_seq[0]
        merge_map[mc] = mc
        m_order_c.append(mc)
        m_order_a.append(0)

        segments.append(elim_seq[:-1])
        supers.append(mc)

        for sc in elim_seq[:-1]:
            merge_map[sc] = mc
        
        mc = elim_seq[-1]
        merge_map[mc] = mc
        segments.append([mc])
        
        m_order_c.append(mc)
        m_order_a.append(0)


def merge_outcome(order_c: list[int], order_a: list[int], \
    order_q: dict[int, tuple[int, int]], rem: list[int]) -> tuple[list[int], \
    list[int], dict[int, tuple[int, int]], dict[int, int], list[int]]:
    merge_map: dict[int, int] = {}

    # We reformulate the prefix order (order_c and order_a) into its merged
    # representation
    m_order_c: list[int] = []
    m_order_a: list[int] = []

    # List of ids corresponding to the new merged candidates.
    supers: list[int] = []

    # Find blocks of at least 3 eliminations in order_a
    elim_seq: list[int] = []

    # Partition order_c into segments according to which candidates will
    # be merged together. For example, segments = [[1],[2,3,4],[5]] will
    # indicate that candidates 1 and 5 remain 'un-merged', but candidates
    # 2-4 will be merged to create a new candidate (with id 2).
    segments: list[list[int]] = []
    for i in range(len(order_a)):
        ci = order_c[i]
        if order_a[i] == 1:
            if elim_seq != []:
                # Merge candidates in elim_seq, add to segments and create
                # an entry for the merged candidate in m_order_c and 
                # m_order_a. Indicate that the original candidates are now
                # mapped to a new identifier in merge_map.
                # Note: we actually leave the first candidate in elim_seq
                # un-merged, and merge the remainder, to support creating 
                # a tighter optimisation problem.
                add_elim_sequence(elim_seq, m_order_c, m_order_a,\
                    merge_map, segments, supers, merge_all=True)

                elim_seq = []

            m_order_c.append(ci)
            m_order_a.append(1)
            merge_map[ci] = ci
            segments.append([ci])

        else:
            elim_seq.append(ci)

    if elim_seq != []:
        # Merge candidates in elim_seq, add to segments and create an entry for
        # the merged candidate in m_order_c and m_order_a. Indicate that the
        # original candidates are now mapped to a new identifier in merge_map.
        # Note: we actually leave the first candidate in elim_seq
        # un-merged, and merge the remainder, to support creating 
        # a tighter optimisation problem.
        add_elim_sequence(elim_seq, m_order_c, m_order_a, merge_map, \
            segments, supers, merge_all=False)
        
    # Create a map between old round numbers and new ones
    round_conv = {-1 : -1}
    j = 0
   
    #print(segments) 
    for r in range(len(segments)):
        for c in segments[r]:
            round_conv[j] = r
     #       print("{} -> {}".format(j, r))
            j += 1

    # Create merged version of order_q, note no candidates that will end
    # up being merged will have an entry in m_order_q.
    for c,(lo,hi) in order_q.items():
        if not lo in round_conv or not hi in round_conv:
            print("({},{}) {}, {}/{}, {}/{}".format(lo, hi, round_conv,
                m_order_c, m_order_a, order_c, order_a))

    m_order_q = { c : (round_conv[lo], round_conv[hi]) \
        for c,(lo,hi) in order_q.items() }

    for r in rem:
        merge_map[r] = r

    return m_order_c, m_order_a, m_order_q, merge_map, supers


def get_order_q(order_a: list[int], LAST_ROUND: int, \
    winners: Iterable[int], order_c_index: dict[int, int]) \
    -> dict[int, tuple[int, int]]:
    """
        Determine the earliest and latest time that winners could have
        achieved a quota, given that we have determined we only care
        about winners that have been seated at or before LAST_ROUND.
    """
    order_q = {}
    for w in winners:
        pos = order_c_index[w]
        if pos == -1:
            pos = LAST_ROUND
        if pos > LAST_ROUND:
            continue

        minrq = pos - 1
        maxrq = pos - 1

        for r in range(pos - 1, -1, -1):
            if order_a[r] == 1:
                minrq -= 1
            else:
                break

        order_q[w] = (minrq, maxrq)

    return order_q
 
