import sys
import os


datafiles = [
    # SCOTLAND 2007
    ("Scotland/GCC_07_Anderson_ballots.txt", 4), ("Scotland/GCC_07_Baillieston_ballots.txt", 4),
    ("Scotland/GCC_07_Calton_ballots.txt", 3), ("Scotland/GCC_07_Canal_ballots.txt", 4),
    ("Scotland/GCC_07_Craigton_ballots.txt", 4), ("Scotland/GCC_07_Drumchapel_ballots.txt", 4),
    ("Scotland/GCC_07_EastCentre_ballots.txt", 4), ("Scotland/GCC_07_Garscadden_ballots.txt", 4),
    ("Scotland/GCC_07_Govan_ballots.txt", 4), ("Scotland/GCC_07_GreaterPollock_ballots.txt", 4),
    ("Scotland/GCC_07_Hillhead_ballots.txt", 4), ("Scotland/GCC_07_Langside_ballots.txt", 3),
    ("Scotland/GCC_07_Linn_ballots.txt", 4), ("Scotland/GCC_07_Maryhill_ballots.txt", 4),
    ("Scotland/GCC_07_Newlands_ballots.txt", 3), ("Scotland/GCC_07_NorthEast_ballots.txt", 4),
    ("Scotland/GCC_07_Partick_ballots.txt", 4), ("Scotland/GCC_07_Pollockshields_ballots.txt", 3),
    ("Scotland/GCC_07_Shettleston_ballots.txt", 4), ("Scotland/GCC_07_SouthsideCentral_ballots.txt", 4),
    ("Scotland/GCC_07_Springburn_ballots.txt", 3),
    # AUSTRALIA 2016, 2019, 2022
    ("FedAus/federal_2016_ACT.stv", 2), ("FedAus/federal_2016_NT.stv", 2),
    ("FedAus/federal_2019_ACT.stv", 2), ("FedAus/federal_2019_NT.stv", 2),
    ("FedAus22/2022NT.json", 2), ("FedAus22/2022ACT.json", 2)
]


reps = 5
counter = 0


if __name__ == "__main__":
    print("datafile, candidates, seats, quota, init_ub, found_lb, found_ub, nodes_exp, minlps_solved, solve(s), time(s)")
    for (datafile, seats) in datafiles:
        counter += 1
        if counter != int(os.environ['SLURM_ARRAY_TASK_ID']): continue
        path = "../stv-rla/data/" + datafile
        sys.argv = ['', '-lse', '-d', path, '-log', f"log_{datafile.replace('/', '')}.log", '-s', str(seats), '-m', '-pc', '8', '-g', '0.05', '-agap', '1']
        for _ in range(reps):
            exec(open("pymarginstv.py").read())
