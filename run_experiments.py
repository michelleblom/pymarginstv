import sys
import os
import glob
from utils import read_ballots_stv, read_ballots_txt, read_ballots_json, read_ballots_blt

displaynames = {
    # SCOTLAND GLASGOW 2007
    "Scotland/GCC_07_Anderson_ballots.txt": "Anderston/City 07",
    "Scotland/GCC_07_Baillieston_ballots.txt": "Baillieston 07",
    "Scotland/GCC_07_Calton_ballots.txt": "Calton 07",
    "Scotland/GCC_07_Canal_ballots.txt": "Canal 07",
    "Scotland/GCC_07_Craigton_ballots.txt": "Craigton 07",
    "Scotland/GCC_07_Drumchapel_ballots.txt": "Drumchapel/Anniesland 07",
    "Scotland/GCC_07_EastCentre_ballots.txt": "East Centre 07",
    "Scotland/GCC_07_Garscadden_ballots.txt": "Garscadden/Scotstounhill 07",
    "Scotland/GCC_07_Govan_ballots.txt": "Govan 07",
    "Scotland/GCC_07_GreaterPollock_ballots.txt": "Greater Pollok 07",
    "Scotland/GCC_07_Hillhead_ballots.txt": "Hillhead 07",
    "Scotland/GCC_07_Langside_ballots.txt": "Langside 07",
    "Scotland/GCC_07_Linn_ballots.txt": "Linn 07",
    "Scotland/GCC_07_Maryhill_ballots.txt": "Maryhill/Kelvin 07",
    "Scotland/GCC_07_Newlands_ballots.txt": "Newlands/Auldburn 07",
    "Scotland/GCC_07_NorthEast_ballots.txt": "North East 07",
    "Scotland/GCC_07_Partick_ballots.txt": "Partick West 07",
    "Scotland/GCC_07_Pollockshields_ballots.txt": "Pollokshields 07",
    "Scotland/GCC_07_Shettleston_ballots.txt": "Shettleston 07",
    "Scotland/GCC_07_SouthsideCentral_ballots.txt": "Southside Central 07",
    "Scotland/GCC_07_Springburn_ballots.txt": "Springburn 07",
    # IRELAND 2002
    "Ireland/DublinNorth2002_ballots.txt": "Dublin North",
    "Ireland/DublinWest2002_ballots.txt": "Dublin West",
    "Ireland/Meath2002_ballots.txt": "Meath",
    # MIXED, SCOTLAND 2022
    "Scotland/2022/PreferenceProfile_V0001_Ward_11___City_Centre_06052022_155600.blt": "City Centre",
    "Scotland/2022/PreferenceProfile_V0001_Ward_12___Leith_Walk_06052022_160625.blt": "Leith Walk",
    "Scotland/2022/PreferenceProfile_V0001_Ward-3-Greater-Pollok_06052022_163750.blt": "Greater Pollok",
    "Scotland/2022/PreferenceProfile_V0001_Ward-18-East-Centre_06052022_165259.blt": "East Centre",
    "Scotland/2022/PreferenceProfile_V0001_Ward-5-Govan_06052022_165258.blt": "Govan",
    "Scotland/2022/preferenceprofile_v0001_ward-19-mearns_06052022_172124.blt": "Mearns",
    "Scotland/2022/preferenceprofile_v0004_ward-4-oban-south-and-the-isles_06052022_143143.blt": "Oban South and The Isles",
    "Scotland/2022/PreferenceProfile_V0001_Ward_5___Inverleith_06052022_155559.blt": "Inverleith",
    "Scotland/2022/PreferenceProfile_V0001_Ward_16___Liberton_Gilmerton_06052022_160625.blt": "Liberton/Gilberton",
    "Scotland/2022/PreferenceProfile_V0001_Ward-6-Pollokshields_06052022_170301.blt": "Pollokshields",
    "Scotland/2022/PreferenceProfile_V0001_Ward-4-Dunfermline-South_06052022_151924.blt": "Dunfermline South",
    "Scotland/2022/PreferenceProfile_V0001_Ward-8-Southside-Central_06052022_165258.blt": "Southside Central",
    "Scotland/2022/PreferenceProfile_V0001_Ward-2-Newlands-Auldburn_06052022_165250.blt": "Newlands/Auldburn",
    "Scotland/2022/PreferenceProfile_V0001_Ward-14-Drumchapel-Anniesland_06052022_170258.blt": "Drumchapel/Anniesland",
    "Scotland/2022/preferenceprofile_v0001_ward-3-dunblane-and-bridge-of-allan_06052022_124253.blt": "Dunblane and Bridge of Allan",
    "Scotland/2022/PreferenceProfile_V0001_Ward-6---Arbroath-West-Letham-and-Friockheim_06052022_150511.blt": "Arbroath West, Letham and Friockheim",
    "Scotland/2022/PreferenceProfile_V0001_Ward-1-West-Fife-and-Coastal-Villages_06052022_145537.blt": "West Fife and Coastal Villages",
    "Scotland/2022/PreferenceProfile_V0001_Ward-10-Anderston-City-Yorkhill_06052022_170256.blt": "Anderston/City/Yorkhill",
    "Scotland/2022/PreferenceProfile_V0001_Ward-16-Canal_06052022_163755.blt": "Canal",
    # AUSTRALIA 2016, 2019, 2022
    "FedAus/federal_2016_ACT.stv": "ACT 16",
    "FedAus/federal_2016_NT.stv": "NT 16",
    "FedAus/federal_2019_ACT.stv": "ACT 19",
    "FedAus/federal_2019_NT.stv": "NT 19",
    "FedAus22/2022NT.json": "NT 22",
    "FedAus22/2022ACT.json": "ACT 22",
    "FederalSenate2022TAS.json": "TAS 22",
    # Minneapolis
    "Minneapolis/MPLS-2009-BET_2Seat_ParsedMB.txt": "Minneapolis BET 09",
    "Minneapolis/MPLS-2013-BET_2Seat_ParsedMB.txt": "Minneapolis BET 13",
    "Minneapolis/MPLS-2017-BET_2Seat_ParsedMB.txt": "Minneapolis BET 17",
    "Minneapolis/MPLS-2021-BET_2Seat_ParsedMB.txt": "Minneapolis BET 21",
}

datafiles = [
    # GLASGOW, SCOTLAND 2007
    # ("Scotland/GCC_07_Anderson_ballots.txt", 4), ("Scotland/GCC_07_Baillieston_ballots.txt", 4),
    # ("Scotland/GCC_07_Calton_ballots.txt", 3), ("Scotland/GCC_07_Canal_ballots.txt", 4),
    # ("Scotland/GCC_07_Craigton_ballots.txt", 4), ("Scotland/GCC_07_Drumchapel_ballots.txt", 4),
    # ("Scotland/GCC_07_EastCentre_ballots.txt", 4), ("Scotland/GCC_07_Garscadden_ballots.txt", 4),
    # ("Scotland/GCC_07_Govan_ballots.txt", 4), ("Scotland/GCC_07_GreaterPollock_ballots.txt", 4),
    # ("Scotland/GCC_07_Hillhead_ballots.txt", 4), ("Scotland/GCC_07_Langside_ballots.txt", 3),
    # ("Scotland/GCC_07_Linn_ballots.txt", 4), ("Scotland/GCC_07_Maryhill_ballots.txt", 4),
    # ("Scotland/GCC_07_Newlands_ballots.txt", 3), ("Scotland/GCC_07_NorthEast_ballots.txt", 4),
    # ("Scotland/GCC_07_Partick_ballots.txt", 4), ("Scotland/GCC_07_Pollockshields_ballots.txt", 3),
    # ("Scotland/GCC_07_Shettleston_ballots.txt", 4), ("Scotland/GCC_07_SouthsideCentral_ballots.txt", 4),
    # ("Scotland/GCC_07_Springburn_ballots.txt", 3),
    # IRELAND 2002
    # ("Ireland/DublinNorth2002_ballots.txt", 4), ("Ireland/DublinWest2002_ballots.txt", 3),
    ("Ireland/Meath2002_ballots.txt", 5),
    # MIXED, SCOTLAND 2022
    # ("Scotland/2022/PreferenceProfile_V0001_Ward_11___City_Centre_06052022_155600.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward_12___Leith_Walk_06052022_160625.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-3-Greater-Pollok_06052022_163750.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-18-East-Centre_06052022_165259.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-5-Govan_06052022_165258.blt", 4),
    # ("Scotland/2022/preferenceprofile_v0001_ward-19-mearns_06052022_172124.blt", 4),
    ("Scotland/2022/preferenceprofile_v0004_ward-4-oban-south-and-the-isles_06052022_143143.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward_5___Inverleith_06052022_155559.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward_16___Liberton_Gilmerton_06052022_160625.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-6-Pollokshields_06052022_170301.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-4-Dunfermline-South_06052022_151924.blt", 3),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-8-Southside-Central_06052022_165258.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-2-Newlands-Auldburn_06052022_165250.blt", 3),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-14-Drumchapel-Anniesland_06052022_170258.blt", 4),
    # ("Scotland/2022/preferenceprofile_v0001_ward-3-dunblane-and-bridge-of-allan_06052022_124253.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-6---Arbroath-West-Letham-and-Friockheim_06052022_150511.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-1-West-Fife-and-Coastal-Villages_06052022_145537.blt", 3),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-10-Anderston-City-Yorkhill_06052022_170256.blt", 4),
    # ("Scotland/2022/PreferenceProfile_V0001_Ward-16-Canal_06052022_163755.blt", 4),
    # AUSTRALIA 2-seat, 2016, 2019, 2022
    ("FedAus/federal_2016_ACT.stv", 2), ("FedAus/federal_2016_NT.stv", 2),
    ("FedAus/federal_2019_ACT.stv", 2), ("FedAus/federal_2019_NT.stv", 2),
    # ("FedAus22/2022NT.json", 2), ("FedAus22/2022ACT.json", 2),
    ("FederalSenate2022TAS.json", 6),
    # Minneapolis
    ("Minneapolis/MPLS-2009-BET_2Seat_ParsedMB.txt", 2),
    ("Minneapolis/MPLS-2013-BET_2Seat_ParsedMB.txt", 2),
    ("Minneapolis/MPLS-2017-BET_2Seat_ParsedMB.txt", 2),
    ("Minneapolis/MPLS-2021-BET_2Seat_ParsedMB.txt", 2),
]

# datafiles = [("Scotland/GCC_07_EastCentre_ballots.txt", 4)]
# datafiles = [("Scotland/2022/preferenceprofile_v0004_ward-4-oban-south-and-the-isles_06052022_143143.blt", 4)]

reps = 3
counter = 0  # 1-135



if __name__ == "__main__":
    print("datafile, candidates, seats, quota, init_ub, found_lb, found_ub, nodes_exp, minlps_solved, solve(s), time(s)")
    for (datafile, seats) in datafiles:
        for version in [0, 1, 2]:
            counter += 1
            if counter != int(os.environ['SLURM_ARRAY_TASK_ID']): continue
            path = "../stv-rla/data/" + datafile
            displayname = displaynames[datafile]
            sys.argv = ['', '-d', path, '-log', f"log_{datafile.replace('/', '')}_{version}.log", '-s', str(seats), '-m', '-pc', '8', '-g', '0.01', '-agap', '0', '-limit', '10800', '-displayname', displayname]
            if version >= 1:
                sys.argv += ['-lse']
            if version >= 2:
                sys.argv += ['-eqlb']
            for _ in range(reps):
                exec(open("pymarginstv.py").read())


# allFiles = glob.glob("/Users/aekk0001/Documents/stv-rla/data/Scotland/2022/*")
#
# for file in allFiles:
#     if file.endswith(".stv"):
#         candidates, ballots, _, cid2num, totvotes = read_ballots_stv(file)
#     elif file.endswith(".blt"):
#         candidates, ballots, _, cid2num, totvotes = read_ballots_blt(file)
#     elif file.endswith(".json"):
#         candidates, ballots, _, cid2num, totvotes = read_ballots_json(file)
#     elif file.endswith(".txt"):
#         candidates, ballots, _, cid2num, totvotes = read_ballots_txt(file)
#     else:
#         continue
#     print(len(candidates), len(ballots), totvotes, file.split("/")[-1])