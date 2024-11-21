import sys
import os
import glob
import json
from utils import read_ballots_stv, read_ballots_txt, read_ballots_json, read_ballots_blt
from subprocess import run

from cProfile import Profile
from pstats import SortKey, Stats


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
    # "Scotland/2022/PreferenceProfile_V0001_Ward_11___City_Centre_06052022_155600.blt": "Edinburgh, City Centre",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_12___Leith_Walk_06052022_160625.blt": "Leith Walk",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-3-Greater-Pollok_06052022_163750.blt": "Greater Pollok",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-18-East-Centre_06052022_165259.blt": "East Centre",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-5-Govan_06052022_165258.blt": "Govan",
    # "Scotland/2022/preferenceprofile_v0001_ward-19-mearns_06052022_172124.blt": "Mearns",
    # "Scotland/2022/preferenceprofile_v0004_ward-4-oban-south-and-the-isles_06052022_143143.blt": "Oban South and The Isles",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_5___Inverleith_06052022_155559.blt": "Inverleith",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_16___Liberton_Gilmerton_06052022_160625.blt": "Liberton/Gilberton",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-6-Pollokshields_06052022_170301.blt": "Pollokshields",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-4-Dunfermline-South_06052022_151924.blt": "Dunfermline South",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-8-Southside-Central_06052022_165258.blt": "Southside Central",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-2-Newlands-Auldburn_06052022_165250.blt": "Newlands/Auldburn",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-14-Drumchapel-Anniesland_06052022_170258.blt": "Drumchapel/Anniesland",
    # "Scotland/2022/preferenceprofile_v0001_ward-3-dunblane-and-bridge-of-allan_06052022_124253.blt": "Dunblane and Bridge of Allan",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-6---Arbroath-West-Letham-and-Friockheim_06052022_150511.blt": "Arbroath West Letham and Friockheim",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-1-West-Fife-and-Coastal-Villages_06052022_145537.blt": "West Fife and Coastal Villages",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-10-Anderston-City-Yorkhill_06052022_170256.blt": "Anderston/City/Yorkhill",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-16-Canal_06052022_163755.blt": "Canal",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-15-Glenrothes-Central-and-Thornton_06052022_145551.blt": "Glenrothes Central and Thornton",
    # "Scotland/2022/preferenceprofile_v0001_ward-6-stirling-east_06052022_124253.blt": "Stirling East",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-3---West-End_06052022_161516.blt": "West End",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-8---The-Ferry_06052022_161517.blt": "The Ferry",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_17___Portobello_Craigmillar_06052022_155600.blt": "Portobello/Craigmillar",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-1-Linn_06052022_163754.blt": "Linn",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_7___East_Kilbride_Central_South.blt": "East Kilbride Central South",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-7-Cowdenbeath_06052022_145532.blt": "Cowdenbeath",
    # "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_1___Musselburgh_06052022_153935.blt": "Musselburgh",
    # "Scotland/2022/PreferenceProfile_V0009_Ward-3---Ayr-North_10052022_111313.blt": "Ayr North",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-3---Forfar-and-District_06052022_150515.blt": "Forfar and District",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_14___Cambuslang_East.blt": "",
    # "Scotland/2022/PreferenceProfile_Ward-4.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-5-peterhead-north-and-rattray_06052022_172118.blt": "",
    # "Scotland/2022/preferenceprofile_v0009_ward-8-isle-of-bute_06052022_165355.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_4___Forth_06052022_160611.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-2-Dunfermline-North_06052022_151927.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-1---Strathmartine_06052022_161516.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-3-Dunfermline-Central_06052022_145551.blt": "",
    # "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_4___North_Berwick_Coastal_06052022_153938.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-19-Shettleston_06052022_170301.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_3___Shetland_West_06052022_120841.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Black_Isle_06052022_161539.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-1---Troon_06052022_142627.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-4-central-buchan_06052022_172124.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-10-Kirkcaldy-North_06052022_151928.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-15-Maryhill_06052022_165258.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-2---Lochee_06052022_161513.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-4-Cardonald_06052022_163754.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Torry-Ferryhill-Ward_06052022_160545.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-4---Monifieth-and-Sidlaw_06052022_150515.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Inverness_West_06052022_161539.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-19-East-Neuk-and-Landward_06052022_145551.blt": "",
    # "Scotland/2022/cnesair_ward09_preferenceprofile.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-14-Glenrothes-North-Leslie-and-Markinch_06052022_151925.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Tillydrone-Seaton-Old-Aberdeen-Ward_06052022_160546.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-3-dumbarton_06052022_120059.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_9___East_Kilbride_West.blt": "",
    # "Scotland/2022/falkirk22_Preference Profile_w9.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-5---Maryfield_06052022_161515.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-20-Cupar_06052022_151928.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-7-Langside_06052022_165250.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_3___Clydesdale_East.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-2-leven_06052022_120059.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-8---Montrose-and-District_06052022_150515.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-4---Ayr-East_06052022_142626.blt": "",
    # "Scotland/2022/orkney22-W2.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Northfield-Mastrick-North-Ward_06052022_160545.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Badenoch_and_Strathspey_06052022_161540.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Nairn_and_Cawdor_06052022_161539.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Bridge-of-Don-Ward_06052022_160546.blt": "",
    # "Scotland/2022/Ward_6_Midlothian_South_Dalkeith_preference_profile__open_from_within_MS_Word_or_similar_.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-17-Tay-Bridgehead_06052022_145551.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-5-Rosyth_06052022_145544.blt": "",
    # "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_5___Haddington_and_Lammermuir_06052022_153938.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-17-Springburn-Robroyston_06052022_170301.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-21-Leven-Kennoway-and-Largo_06052022_145552.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Cromarty_Firth_06052022_161538.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-7-bannockburn_06052022_124254.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-10-west-garioch_06052022_172124.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-5---Ayr-West_06052022_142628.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-18-stonehaven-and-lower-deeside_06052022_172124.blt": "",
    # "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_3___Tranent_Wallyford_and_Macmerry_06052022_153937.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-4---Coldside_06052022_161514.blt": "",
    # "Scotland/2022/falkirk22_Preference Profile_W2.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Inverness_Central_06052022_161539.blt": "",
    # "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_2___Preston_Seton_and_Gosford_06052022_153931.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-2---Prestwick_06052022_142624.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-9-Calton_06052022_163749.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_13___Leith_06052022_155600.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-1-trossachs-and-teith_06052022_124254.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Dyce-Bucksburn-Danestone-Ward_06052022_160545.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_2___Pentland_Hills_06052022_160611.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-9-Burntisland-Kinghorn-and-Western-Kirkcaldy_06052022_145551.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-1-banff-and-district_06052022_172114.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-23-Partick-East-Kelvindale_06052022_170257.blt": "",
    # "Scotland/2022/preferenceprofile_v0003_ward-3-mid-argyll_06052022_133803.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_6___East_Kilbride_South.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-6-Inverkeithing-and-Dalgety-Bay_06052022_151927.blt": "",
    # "Scotland/2022/cnesair_ward02_preferenceprofile.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Kincorth-Nigg-Cove-Ward_06052022_160546.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-2-forth-and-endrick_06052022_124253.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_7___Sighthill_Gorgie_06052022_155557.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-21-North-East_06052022_170301.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Eilean_a__Che___06052022_161539.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-22-Buckhaven-Methil-and-Wemyss-Villages_06052022_151928.blt": "",
    # "Scotland/2022/clacks_W2_North_2022_6694.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-4---Castle-Douglas-and-Crocketford_06052022_171202.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_20___Larkhall.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-12-Kirkcaldy-East_06052022_151925.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_3___Drum_Brae_Gyle_06052022_155559.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_1___Almond_06052022_155516.blt": "",
    # "Scotland/2022/preferenceprofile_v0005_ward-5-oban-north-and-lorn_06052022_151453.blt": "",
    # "Scotland/2022/preferenceprofile_v0001_ward-17-north-kincardine_06052022_172124.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-8-Lochgelly-Cardenden-and-Benarty_06052022_151928.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward_4___Clydesdale_South.blt": "",
    # "Scotland/2022/PreferenceProfile_V0001_Ward-13-Garscadden-Scotstounhill_06052022_165250.blt": "",
    "Scotland/2022/PreferenceProfile_V0001_Airyhall-Broomhill-Garthdee-Ward_06052022_160546.blt": "Aberdeen-Airyhall-Broomhill-Garthdee",
    "Scotland/2022/PreferenceProfile_V0001_Bridge-of-Don-Ward_06052022_160546.blt": "Aberdeen-Bridge-of-Don",
    "Scotland/2022/PreferenceProfile_V0001_Dyce-Bucksburn-Danestone-Ward_06052022_160545.blt": "Aberdeen-Dyce-Bucksburn-Danestone",
    "Scotland/2022/PreferenceProfile_V0001_George-St-Harbour-Ward_06052022_160545.blt": "Aberdeen-George-St-Harbour",
    "Scotland/2022/PreferenceProfile_V0001_Hazlehead-Queens-Cross-Countesswells-Ward_06052022_160545.blt": "Aberdeen-Hazlehead-Queens-Cross-Countesswells",
    "Scotland/2022/PreferenceProfile_V0001_Hilton-Woodside-Stockethill-Ward_06052022_160546.blt": "Aberdeen-Hilton-Woodside-Stockethill",
    "Scotland/2022/PreferenceProfile_V0001_Kincorth-Nigg-Cove-Ward_06052022_160546.blt": "Aberdeen-Kincorth-Nigg-Cove",
    "Scotland/2022/PreferenceProfile_V0001_Kingswells-Sheddocksley-Summerhill-Ward_06052022_160546.blt": "Aberdeen-Kingswells-Sheddocksley-Summerhill",
    "Scotland/2022/PreferenceProfile_V0001_Lower-Deeside-Ward_06052022_160546.blt": "Aberdeen-Lower-Deeside",
    "Scotland/2022/PreferenceProfile_V0001_Midstocket-Rosemount-Ward_06052022_160545.blt": "Aberdeen-Midstocket-Rosemount",
    "Scotland/2022/PreferenceProfile_V0001_Northfield-Mastrick-North-Ward_06052022_160545.blt": "Aberdeen-Northfield-Mastrick-North",
    "Scotland/2022/PreferenceProfile_V0001_Tillydrone-Seaton-Old-Aberdeen-Ward_06052022_160546.blt": "Aberdeen-Tillydrone-Seaton-Old-Aberdeen",
    "Scotland/2022/PreferenceProfile_V0001_Torry-Ferryhill-Ward_06052022_160545.blt": "Aberdeen-Torry-Ferryhill",
    "Scotland/2022/preferenceprofile_v0001_ward-1-banff-and-district_06052022_172114.blt": "Aberdeenshire-ward-1-banff-and-district",
    "Scotland/2022/preferenceprofile_v0001_ward-10-west-garioch_06052022_172124.blt": "Aberdeenshire-ward-10-west-garioch",
    "Scotland/2022/preferenceprofile_v0001_ward-11-inverurie-and-district_06052022_172124.blt": "Aberdeenshire-ward-11-inverurie-and-district",
    "Scotland/2022/preferenceprofile_v0001_ward-12-east-garioch_06052022_172124.blt": "Aberdeenshire-ward-12-east-garioch",
    "Scotland/2022/preferenceprofile_v0001_ward-13-westhill-and-district_06052022_172124.blt": "Aberdeenshire-ward-13-westhill-and-district",
    "Scotland/2022/preferenceprofile_v0001_ward-14-huntly-strathbogie-and-howe-of-alford_06052022_172124.blt": "Aberdeenshire-ward-14-huntly-strathbogie-and-howe-of-alford",
    "Scotland/2022/preferenceprofile_v0001_ward-15-aboyne-upper-deeside-and-donside_06052022_172124.blt": "Aberdeenshire-ward-15-aboyne-upper-deeside-and-donside",
    "Scotland/2022/preferenceprofile_v0001_ward-16-banchory-and-mid-deeside_06052022_172124.blt": "Aberdeenshire-ward-16-banchory-and-mid-deeside",
    "Scotland/2022/preferenceprofile_v0001_ward-17-north-kincardine_06052022_172124.blt": "Aberdeenshire-ward-17-north-kincardine",
    "Scotland/2022/preferenceprofile_v0001_ward-18-stonehaven-and-lower-deeside_06052022_172124.blt": "Aberdeenshire-ward-18-stonehaven-and-lower-deeside",
    "Scotland/2022/preferenceprofile_v0001_ward-19-mearns_06052022_172124.blt": "Aberdeenshire-ward-19-mearns",
    "Scotland/2022/preferenceprofile_v0001_ward-2-troup_06052022_172123.blt": "Aberdeenshire-ward-2-troup",
    "Scotland/2022/preferenceprofile_v0001_ward-3-fraserburgh-and-district_06052022_172124.blt": "Aberdeenshire-ward-3-fraserburgh-and-district",
    "Scotland/2022/preferenceprofile_v0001_ward-4-central-buchan_06052022_172124.blt": "Aberdeenshire-ward-4-central-buchan",
    "Scotland/2022/preferenceprofile_v0001_ward-5-peterhead-north-and-rattray_06052022_172118.blt": "Aberdeenshire-ward-5-peterhead-north-and-rattray",
    "Scotland/2022/preferenceprofile_v0001_ward-6-peterhead-south-and-cruden_06052022_172115.blt": "Aberdeenshire-ward-6-peterhead-south-and-cruden",
    "Scotland/2022/preferenceprofile_v0001_ward-7-turriff-and-district_06052022_172118.blt": "Aberdeenshire-ward-7-turriff-and-district",
    "Scotland/2022/preferenceprofile_v0001_ward-8-mid-formartine_06052022_172123.blt": "Aberdeenshire-ward-8-mid-formartine",
    "Scotland/2022/preferenceprofile_v0001_ward-9-ellon-and-district_06052022_172124.blt": "Aberdeenshire-ward-9-ellon-and-district",
    "Scotland/2022/PreferenceProfile_V0001_Ward-1---Kirriemuir-and-Dean_06052022_150515(1).blt": "Angus-Ward-1 Kirriemuir-and-Dean",
    "Scotland/2022/PreferenceProfile_V0001_Ward-2---Brechin-and-Edzell_06052022_150515.blt": "Angus-Ward-2 Brechin-and-Edzell",
    "Scotland/2022/PreferenceProfile_V0001_Ward-3---Forfar-and-District_06052022_150515.blt": "Angus-Ward-3 Forfar-and-District",
    "Scotland/2022/PreferenceProfile_V0001_Ward-4---Monifieth-and-Sidlaw_06052022_150515.blt": "Angus-Ward-4 Monifieth-and-Sidlaw",
    "Scotland/2022/PreferenceProfile_V0001_Ward-5---Carnoustie-and-District_06052022_150514(1).blt": "Angus-Ward-5 Carnoustie-and-District",
    "Scotland/2022/PreferenceProfile_V0001_Ward-6---Arbroath-West-Letham-and-Friockheim_06052022_150511.blt": "Angus-Ward-6 Arbroath-West-Letham-and-Friockheim",
    "Scotland/2022/PreferenceProfile_V0001_Ward-7---Arbroath-East-and-Lunan_06052022_150515.blt": "Angus-Ward-7 Arbroath-East-and-Lunan",
    "Scotland/2022/PreferenceProfile_V0001_Ward-8---Montrose-and-District_06052022_150515.blt": "Angus-Ward-8 Montrose-and-District",
    "Scotland/2022/preferenceprofile_v0001_ward-1-south-kintyre_06052022_120128.blt": "ArgyllAndBute-ward-1-south-kintyre",
    "Scotland/2022/preferenceprofile_v0002_ward-2-kintyre-and-the-islands_06052022_130502.blt": "ArgyllAndBute-ward-2-kintyre-and-the-islands",
    "Scotland/2022/preferenceprofile_v0003_ward-3-mid-argyll_06052022_133803.blt": "ArgyllAndBute-ward-3-mid-argyll",
    "Scotland/2022/preferenceprofile_v0004_ward-4-oban-south-and-the-isles_06052022_143143.blt": "ArgyllAndBute-ward-4-oban-south-and-the-isles",
    "Scotland/2022/preferenceprofile_v0005_ward-5-oban-north-and-lorn_06052022_151453.blt": "ArgyllAndBute-ward-5-oban-north-and-lorn",
    "Scotland/2022/preferenceprofile_v0007_ward-6-cowal_06052022_160055.blt": "ArgyllAndBute-ward-6-cowal",
    "Scotland/2022/preferenceprofile_v0008_ward-7-dunoon_06052022_163322.blt": "ArgyllAndBute-ward-7-dunoon",
    "Scotland/2022/preferenceprofile_v0009_ward-8-isle-of-bute_06052022_165355.blt": "ArgyllAndBute-ward-8-isle-of-bute",
    "Scotland/2022/preferenceprofile_v0010_ward-9-lomond-north_06052022_173349.blt": "ArgyllAndBute-ward-9-lomond-north",
    "Scotland/2022/preferenceprofile_v0012_ward-10-helensburgh-central_06052022_182005.blt": "ArgyllAndBute-ward-10-helensburgh-central",
    "Scotland/2022/preferenceprofile_v0012_ward-11-helensburgh-and-lomond-south_06052022_182005.blt": "ArgyllAndBute-ward-11-helensburgh-and-lomond-south",
    "Scotland/2022/clacks_W1_West_2022_6693.blt": "Clackmannanshire-Ward 1_West_2022_6693",
    "Scotland/2022/clacks_W2_North_2022_6694.blt": "Clackmannanshire-Ward 2_North_2022_6694",
    "Scotland/2022/clacks_W3_Central_2022_6695.blt": "Clackmannanshire-Ward 3_Central_2022_6695",
    "Scotland/2022/clacks_W4_South_2022_6696.blt": "Clackmannanshire-Ward 4_South_2022_6696",
    "Scotland/2022/clacks_W5_East_2022_6697.blt": "Clackmannanshire-Ward 5_East_2022_6697",
    "Scotland/2022/cnesair_ward02_preferenceprofile.blt": "Comhairle nan Eilean Siar-Ward 02",
    "Scotland/2022/cnesair_ward07_preferenceprofile.blt": "Comhairle nan Eilean Siar-Ward 07",
    "Scotland/2022/cnesair_ward08_preferenceprofile.blt": "Comhairle nan Eilean Siar-Ward 08",
    "Scotland/2022/cnesair_ward09_preferenceprofile.blt": "Comhairle nan Eilean Siar-Ward 09",
    "Scotland/2022/cnesair_ward10_preferenceprofile.blt": "Comhairle nan Eilean Siar-Ward 10",
    "Scotland/2022/cnesair_ward_03_preferenceprofile.blt": "Comhairle nan Eilean Siar-Ward 03",
    "Scotland/2022/cnesair_ward_04_preferenceprofile.blt": "Comhairle nan Eilean Siar-Ward 04",
    "Scotland/2022/cnesair_ward_05_preferenceprofile.blt": "Comhairle nan Eilean Siar-Ward 05",
    "Scotland/2022/PreferenceProfile_V0001_Ward-1---Stranraer-and-the-Rhins_06052022_171141.blt": "DumfriesAndGalloway-Ward-1 Stranraer-and-the-Rhins",
    "Scotland/2022/PreferenceProfile_V0001_Ward-1---Strathmartine_06052022_161516.blt": "DumfriesAndGalloway-Ward-1 Strathmartine",
    "Scotland/2022/PreferenceProfile_V0001_Ward-10---Annandale-South_06052022_171202.blt": "DumfriesAndGalloway-Ward-10 Annandale-South",
    "Scotland/2022/PreferenceProfile_V0001_Ward-11---Annandale-North_06052022_171202.blt": "DumfriesAndGalloway-Ward-11 Annandale-North",
    "Scotland/2022/PreferenceProfile_V0001_Ward-12---Annandale-East-and-Eskdale_06052022_171202.blt": "DumfriesAndGalloway-Ward-12 Annandale-East-and-Eskdale",
    "Scotland/2022/PreferenceProfile_V0001_Ward-2---Lochee_06052022_161513.blt": "DumfriesAndGalloway-Ward-2 Lochee",
    "Scotland/2022/PreferenceProfile_V0001_Ward-2---Mid-Galloway-and-Wigtown-West_06052022_171201.blt": "DumfriesAndGalloway-Ward-2 Mid-Galloway-and-Wigtown-West",
    "Scotland/2022/PreferenceProfile_V0001_Ward-3---Dee-and-Glenkens_06052022_171147.blt": "DumfriesAndGalloway-Ward-3 Dee-and-Glenkens",
    "Scotland/2022/PreferenceProfile_V0001_Ward-3---West-End_06052022_161516.blt": "DumfriesAndGalloway-Ward-3 West-End",
    "Scotland/2022/PreferenceProfile_V0001_Ward-4---Castle-Douglas-and-Crocketford_06052022_171202.blt": "DumfriesAndGalloway-Ward-4 Castle-Douglas-and-Crocketford",
    "Scotland/2022/PreferenceProfile_V0001_Ward-4---Coldside_06052022_161514.blt": "DumfriesAndGalloway-Ward-4 Coldside",
    "Scotland/2022/PreferenceProfile_V0001_Ward-5---Abbey_06052022_171201.blt": "DumfriesAndGalloway-Ward-5 Abbey",
    "Scotland/2022/PreferenceProfile_V0001_Ward-5---Maryfield_06052022_161515.blt": "DumfriesAndGalloway-Ward-5 Maryfield",
    "Scotland/2022/PreferenceProfile_V0001_Ward-6---North-East_06052022_161516.blt": "DumfriesAndGalloway-Ward-6 North-East",
    "Scotland/2022/PreferenceProfile_V0001_Ward-6---North-West-Dumfries_06052022_171201.blt": "DumfriesAndGalloway-Ward-6 North-West-Dumfries",
    "Scotland/2022/PreferenceProfile_V0001_Ward-7---East-End_06052022_161516.blt": "DumfriesAndGalloway-Ward-7 East-End",
    "Scotland/2022/PreferenceProfile_V0001_Ward-7---Mid-and-Upper-Nithsdale_06052022_171202.blt": "DumfriesAndGalloway-Ward-7 Mid-and-Upper-Nithsdale",
    "Scotland/2022/PreferenceProfile_V0001_Ward-8---Lochar_06052022_171202.blt": "DumfriesAndGalloway-Ward-8 Lochar",
    "Scotland/2022/PreferenceProfile_V0001_Ward-8---The-Ferry_06052022_161517.blt": "DumfriesAndGalloway-Ward-8 The-Ferry",
    "Scotland/2022/PreferenceProfile_V0001_Ward-9---Nith_06052022_171202.blt": "DumfriesAndGalloway-Ward-9 Nith",
    "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_1___Musselburgh_06052022_153935.blt": "EastLothian-Ward_1 Musselburgh",
    "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_2___Preston_Seton_and_Gosford_06052022_153931.blt": "EastLothian-Ward_2 Preston_Seton_and_Gosford",
    "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_3___Tranent_Wallyford_and_Macmerry_06052022_153937.blt": "EastLothian-Ward_3 Tranent_Wallyford_and_Macmerry",
    "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_4___North_Berwick_Coastal_06052022_153938.blt": "EastLothian-Ward_4 North_Berwick_Coastal",
    "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_5___Haddington_and_Lammermuir_06052022_153938.blt": "EastLothian-Ward_5 Haddington_and_Lammermuir",
    "Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_6___Dunbar_and_East_Linton_06052022_153938.blt": "EastLothian-Ward_6 Dunbar_and_East_Linton",
    "Scotland/2022/PreferenceProfile_V0001_Ward_10___Morningside_06052022_160625.blt": "Edinburgh-Ward_10 Morningside",
    "Scotland/2022/PreferenceProfile_V0001_Ward_11___City_Centre_06052022_155600.blt": "Edinburgh-Ward_11 City_Centre",
    "Scotland/2022/PreferenceProfile_V0001_Ward_12___Leith_Walk_06052022_160625.blt": "Edinburgh-Ward_12 Leith_Walk",
    "Scotland/2022/PreferenceProfile_V0001_Ward_13___Leith_06052022_155600.blt": "Edinburgh-Ward_13 Leith",
    "Scotland/2022/PreferenceProfile_V0001_Ward_14___Craigentinny_Duddingston_06052022_160625.blt": "Edinburgh-Ward_14 Craigentinny_Duddingston",
    "Scotland/2022/PreferenceProfile_V0001_Ward_15___Southside_Newington_06052022_155603.blt": "Edinburgh-Ward_15 Southside_Newington",
    "Scotland/2022/PreferenceProfile_V0001_Ward_16___Liberton_Gilmerton_06052022_160625.blt": "Edinburgh-Ward_16 Liberton_Gilmerton",
    "Scotland/2022/PreferenceProfile_V0001_Ward_17___Portobello_Craigmillar_06052022_155600.blt": "Edinburgh-Ward_17 Portobello_Craigmillar",
    "Scotland/2022/PreferenceProfile_V0001_Ward_1___Almond_06052022_155516.blt": "Edinburgh-Ward_1 Almond",
    "Scotland/2022/PreferenceProfile_V0001_Ward_2___Pentland_Hills_06052022_160611.blt": "Edinburgh-Ward_2 Pentland_Hills",
    "Scotland/2022/PreferenceProfile_V0001_Ward_3___Drum_Brae_Gyle_06052022_155559.blt": "Edinburgh-Ward_3 Drum_Brae_Gyle",
    "Scotland/2022/PreferenceProfile_V0001_Ward_4___Forth_06052022_160611.blt": "Edinburgh-Ward_4 Forth",
    "Scotland/2022/PreferenceProfile_V0001_Ward_5___Inverleith_06052022_155559.blt": "Edinburgh-Ward_5 Inverleith",
    "Scotland/2022/PreferenceProfile_V0001_Ward_6___Corstorphine_Murrayfield_06052022_160625.blt": "Edinburgh-Ward_6 Corstorphine_Murrayfield",
    "Scotland/2022/PreferenceProfile_V0001_Ward_7___Sighthill_Gorgie_06052022_155557.blt": "Edinburgh-Ward_7 Sighthill_Gorgie",
    "Scotland/2022/PreferenceProfile_V0001_Ward_8___Colinton_Fairmilehead_06052022_160625.blt": "Edinburgh-Ward_8 Colinton_Fairmilehead",
    "Scotland/2022/PreferenceProfile_V0001_Ward_9___Fountainbridge_Craiglockhart_06052022_155600.blt": "Edinburgh-Ward_9 Fountainbridge_Craiglockhart",
    "Scotland/2022/falkirk22_Preference Profile_W1.blt": "Falkirk-Ward 1",
    "Scotland/2022/falkirk22_Preference Profile_W2.blt": "Falkirk-Ward 2",
    "Scotland/2022/falkirk22_Preference Profile_W3.blt": "Falkirk-Ward 3",
    "Scotland/2022/falkirk22_Preference Profile_W4.blt": "Falkirk-Ward 4",
    "Scotland/2022/falkirk22_Preference Profile_W5.blt": "Falkirk-Ward 5",
    "Scotland/2022/falkirk22_Preference Profile_w6.blt": "Falkirk-Ward 6",
    "Scotland/2022/falkirk22_Preference Profile_w7.blt": "Falkirk-Ward 7",
    "Scotland/2022/falkirk22_Preference Profile_w8.blt": "Falkirk-Ward 8",
    "Scotland/2022/falkirk22_Preference Profile_w9.blt": "Falkirk-Ward 9",
    "Scotland/2022/PreferenceProfile_V0001_Ward-1-West-Fife-and-Coastal-Villages_06052022_145537.blt": "Fife-Ward-1-West-Fife-and-Coastal-Villages",
    "Scotland/2022/PreferenceProfile_V0001_Ward-10-Kirkcaldy-North_06052022_151928.blt": "Fife-Ward-10-Kirkcaldy-North",
    "Scotland/2022/PreferenceProfile_V0001_Ward-11-Kirkcaldy-Central_06052022_145551.blt": "Fife-Ward-11-Kirkcaldy-Central",
    "Scotland/2022/PreferenceProfile_V0001_Ward-12-Kirkcaldy-East_06052022_151925.blt": "Fife-Ward-12-Kirkcaldy-East",
    "Scotland/2022/PreferenceProfile_V0001_Ward-13-Glenrothes-West-and-Kinglassie_06052022_145551.blt": "Fife-Ward-13-Glenrothes-West-and-Kinglassie",
    "Scotland/2022/PreferenceProfile_V0001_Ward-14-Glenrothes-North-Leslie-and-Markinch_06052022_151925.blt": "Fife-Ward-14-Glenrothes-North-Leslie-and-Markinch",
    "Scotland/2022/PreferenceProfile_V0001_Ward-15-Glenrothes-Central-and-Thornton_06052022_145551.blt": "Fife-Ward-15-Glenrothes-Central-and-Thornton",
    "Scotland/2022/PreferenceProfile_V0001_Ward-16-Howe-Of-Fife-and-Tay-Coast_06052022_151928.blt": "Fife-Ward-16-Howe-Of-Fife-and-Tay-Coast",
    "Scotland/2022/PreferenceProfile_V0001_Ward-17-Tay-Bridgehead_06052022_145551.blt": "Fife-Ward-17-Tay-Bridgehead",
    "Scotland/2022/PreferenceProfile_V0001_Ward-18-St.blt": "Fife-Ward-18-St",
    "Scotland/2022/PreferenceProfile_V0001_Ward-19-East-Neuk-and-Landward_06052022_145551.blt": "Fife-Ward-19-East-Neuk-and-Landward",
    "Scotland/2022/PreferenceProfile_V0001_Ward-2-Dunfermline-North_06052022_151927.blt": "Fife-Ward-2-Dunfermline-North",
    "Scotland/2022/PreferenceProfile_V0001_Ward-20-Cupar_06052022_151928.blt": "Fife-Ward-20-Cupar",
    "Scotland/2022/PreferenceProfile_V0001_Ward-21-Leven-Kennoway-and-Largo_06052022_145552.blt": "Fife-Ward-21-Leven-Kennoway-and-Largo",
    "Scotland/2022/PreferenceProfile_V0001_Ward-22-Buckhaven-Methil-and-Wemyss-Villages_06052022_151928.blt": "Fife-Ward-22-Buckhaven-Methil-and-Wemyss-Villages",
    "Scotland/2022/PreferenceProfile_V0001_Ward-3-Dunfermline-Central_06052022_145551.blt": "Fife-Ward-3-Dunfermline-Central",
    "Scotland/2022/PreferenceProfile_V0001_Ward-4-Dunfermline-South_06052022_151924.blt": "Fife-Ward-4-Dunfermline-South",
    "Scotland/2022/PreferenceProfile_V0001_Ward-5-Rosyth_06052022_145544.blt": "Fife-Ward-5-Rosyth",
    "Scotland/2022/PreferenceProfile_V0001_Ward-6-Inverkeithing-and-Dalgety-Bay_06052022_151927.blt": "Fife-Ward-6-Inverkeithing-and-Dalgety-Bay",
    "Scotland/2022/PreferenceProfile_V0001_Ward-7-Cowdenbeath_06052022_145532.blt": "Fife-Ward-7-Cowdenbeath",
    "Scotland/2022/PreferenceProfile_V0001_Ward-8-Lochgelly-Cardenden-and-Benarty_06052022_151928.blt": "Fife-Ward-8-Lochgelly-Cardenden-and-Benarty",
    "Scotland/2022/PreferenceProfile_V0001_Ward-9-Burntisland-Kinghorn-and-Western-Kirkcaldy_06052022_145551.blt": "Fife-Ward-9-Burntisland-Kinghorn-and-Western-Kirkcaldy",
    "Scotland/2022/PreferenceProfile_V0001_Ward-18-St-Andrews_06052022_151928.blt": "Fife-Ward-18-St-Andrews",
    "Scotland/2022/PreferenceProfile_V0001_Ward-1-Linn_06052022_163754.blt": "Glasgow-Ward-1-Linn",
    "Scotland/2022/PreferenceProfile_V0001_Ward-10-Anderston-City-Yorkhill_06052022_170256.blt": "Glasgow-Ward-10-Anderston-City-Yorkhill",
    "Scotland/2022/PreferenceProfile_V0001_Ward-11-Hillhead_06052022_163755.blt": "Glasgow-Ward-11-Hillhead",
    "Scotland/2022/PreferenceProfile_V0001_Ward-12-Victoria-Park_06052022_163755.blt": "Glasgow-Ward-12-Victoria-Park",
    "Scotland/2022/PreferenceProfile_V0001_Ward-13-Garscadden-Scotstounhill_06052022_165250.blt": "Glasgow-Ward-13-Garscadden-Scotstounhill",
    "Scotland/2022/PreferenceProfile_V0001_Ward-14-Drumchapel-Anniesland_06052022_170258.blt": "Glasgow-Ward-14-Drumchapel-Anniesland",
    "Scotland/2022/PreferenceProfile_V0001_Ward-15-Maryhill_06052022_165258.blt": "Glasgow-Ward-15-Maryhill",
    "Scotland/2022/PreferenceProfile_V0001_Ward-16-Canal_06052022_163755.blt": "Glasgow-Ward-16-Canal",
    "Scotland/2022/PreferenceProfile_V0001_Ward-17-Springburn-Robroyston_06052022_170301.blt": "Glasgow-Ward-17-Springburn-Robroyston",
    "Scotland/2022/PreferenceProfile_V0001_Ward-18-East-Centre_06052022_165259.blt": "Glasgow-Ward-18-East-Centre",
    "Scotland/2022/PreferenceProfile_V0001_Ward-19-Shettleston_06052022_170301.blt": "Glasgow-Ward-19-Shettleston",
    "Scotland/2022/PreferenceProfile_V0001_Ward-2-Newlands-Auldburn_06052022_165250.blt": "Glasgow-Ward-2-Newlands-Auldburn",
    "Scotland/2022/PreferenceProfile_V0001_Ward-20-Baillieston_06052022_170301.blt": "Glasgow-Ward-20-Baillieston",
    "Scotland/2022/PreferenceProfile_V0001_Ward-21-North-East_06052022_170301.blt": "Glasgow-Ward-21-North-East",
    "Scotland/2022/PreferenceProfile_V0001_Ward-22-Dennistoun_06052022_163757.blt": "Glasgow-Ward-22-Dennistoun",
    "Scotland/2022/PreferenceProfile_V0001_Ward-23-Partick-East-Kelvindale_06052022_170257.blt": "Glasgow-Ward-23-Partick-East-Kelvindale",
    "Scotland/2022/PreferenceProfile_V0001_Ward-3-Greater-Pollok_06052022_163750.blt": "Glasgow-Ward-3-Greater-Pollok",
    "Scotland/2022/PreferenceProfile_V0001_Ward-4-Cardonald_06052022_163754.blt": "Glasgow-Ward-4-Cardonald",
    "Scotland/2022/PreferenceProfile_V0001_Ward-5-Govan_06052022_165258.blt": "Glasgow-Ward-5-Govan",
    "Scotland/2022/PreferenceProfile_V0001_Ward-6-Pollokshields_06052022_170301.blt": "Glasgow-Ward-6-Pollokshields",
    "Scotland/2022/PreferenceProfile_V0001_Ward-7-Langside_06052022_165250.blt": "Glasgow-Ward-7-Langside",
    "Scotland/2022/PreferenceProfile_V0001_Ward-8-Southside-Central_06052022_165258.blt": "Glasgow-Ward-8-Southside-Central",
    "Scotland/2022/PreferenceProfile_V0001_Ward-9-Calton_06052022_163749.blt": "Glasgow-Ward-9-Calton",
    "Scotland/2022/PreferenceProfile_V0001_Aird_and_Loch_Ness_06052022_161539.blt": "Highland-Aird_and_Loch_Ness",
    "Scotland/2022/PreferenceProfile_V0001_Badenoch_and_Strathspey_06052022_161540.blt": "Highland-Badenoch_and_Strathspey",
    "Scotland/2022/PreferenceProfile_V0001_Black_Isle_06052022_161539.blt": "Highland-Black_Isle",
    "Scotland/2022/PreferenceProfile_V0001_Cromarty_Firth_06052022_161538.blt": "Highland-Cromarty_Firth",
    "Scotland/2022/PreferenceProfile_V0001_Culloden_and_Ardersier_06052022_161539.blt": "Highland-Culloden_and_Ardersier",
    "Scotland/2022/PreferenceProfile_V0001_Dingwall_and_Seaforth_06052022_161539.blt": "Highland-Dingwall_and_Seaforth",
    "Scotland/2022/PreferenceProfile_V0001_East_Sutherland_and_Edderton_06052022_161530.blt": "Highland-East_Sutherland_and_Edderton",
    "Scotland/2022/PreferenceProfile_V0001_Eilean_a__Che___06052022_161539.blt": "Highland-Eilean_a__Che",
    "Scotland/2022/PreferenceProfile_V0001_Fort_William_and_Ardnamurchan_06052022_161540.blt": "Highland-Fort_William_and_Ardnamurchan",
    "Scotland/2022/PreferenceProfile_V0001_Inverness_Central_06052022_161539.blt": "Highland-Inverness_Central",
    "Scotland/2022/PreferenceProfile_V0001_Inverness_Millburn_06052022_161539.blt": "Highland-Inverness_Millburn",
    "Scotland/2022/PreferenceProfile_V0001_Inverness_Ness_side_06052022_161539.blt": "Highland-Inverness_Ness_side",
    "Scotland/2022/PreferenceProfile_V0001_Inverness_South_06052022_161540.blt": "Highland-Inverness_South",
    "Scotland/2022/PreferenceProfile_V0001_Inverness_West_06052022_161539.blt": "Highland-Inverness_West",
    "Scotland/2022/PreferenceProfile_V0001_Nairn_and_Cawdor_06052022_161539.blt": "Highland-Nairn_and_Cawdor",
    "Scotland/2022/PreferenceProfile_V0001_North_West_and_Central_Sutherland_06052022_161534.blt": "Highland-North_West_and_Central_Sutherland",
    "Scotland/2022/PreferenceProfile_V0001_Tain_and_Easter_Ross_06052022_161537.blt": "Highland-Tain_and_Easter_Ross",
    "Scotland/2022/PreferenceProfile_V0001_Thurso_and_Northwest_Caithness_06052022_161528.blt": "Highland-Thurso_and_Northwest_Caithness",
    "Scotland/2022/PreferenceProfile_V0001_Wester_Ross_Strathpeffer_and_Lochalsh_06052022_161539.blt": "Highland-Wester_Ross_Strathpeffer_and_Lochalsh",
    "Scotland/2022/PreferenceProfile_V0001_Wick_and_East_Caithness_06052022_161532.blt": "Highland-Wick_and_East_Caithness",
    "Scotland/2022/PreferenceProfile_Ward-2.blt": "Inverclyde-Ward-2",
    "Scotland/2022/PreferenceProfile_Ward-3.blt": "Inverclyde-Ward-3",
    "Scotland/2022/PreferenceProfile_Ward-4.blt": "Inverclyde-Ward-4",
    "Scotland/2022/PreferenceProfile_Ward-5.blt": "Inverclyde-Ward-5",
    "Scotland/2022/PreferenceProfile_Ward-6.blt": "Inverclyde-Ward-6",
    "Scotland/2022/PreferenceProfile_Ward-7.blt": "Inverclyde-Ward-7",
    "Scotland/2022/PreferenceProfile_V0001_Ward_2___Bonnyrigg_06052022_151836.blt": "Midlothian-Ward_2 Bonnyrigg",
    "Scotland/2022/Ward_1_Penicuik_preference_profile__open_from_within_MS_Word_or_similar_.blt": "Midlothian-Ward_1_Penicuik",
    "Scotland/2022/Ward_3_Dalkeith_preference_profile__open_from_within_MS_Word_or_similar_.blt": "Midlothian-Ward_3_Dalkeith",
    "Scotland/2022/Ward_4_Midlothian_West_preference_profile__open_from_within_MS_Word_or_similar_.blt": "Midlothian-Ward_4_Midlothian_West",
    "Scotland/2022/Ward_5_Midlothian_East_preference_profile__open_from_within_MS_Word_or_similar_.blt": "Midlothian-Ward_5_Midlothian_East",
    "Scotland/2022/Ward_6_Midlothian_South_Dalkeith_preference_profile__open_from_within_MS_Word_or_similar_.blt": "Midlothian-Ward_6_Midlothian_South_Dalkeith",
    "Scotland/2022/moray22_ward1.blt": "Moray-Ward 1",
    "Scotland/2022/moray22_ward2.blt": "Moray-Ward 2",
    "Scotland/2022/moray22_ward4.blt": "Moray-Ward 4",
    "Scotland/2022/moray22_ward5.blt": "Moray-Ward 5",
    "Scotland/2022/moray22_ward6.blt": "Moray-Ward 6",
    "Scotland/2022/moray22_ward7.blt": "Moray-Ward 7",
    "Scotland/2022/moray22_ward8.blt": "Moray-Ward 8",
    "Scotland/2022/orkney22-W2.blt": "OrkneyIslands-Ward 2",
    "Scotland/2022/orkney22-W3.blt": "OrkneyIslands-Ward 3",
    "Scotland/2022/orkney22-W4.blt": "OrkneyIslands-Ward 4",
    "Scotland/2022/orkney22-W5.blt": "OrkneyIslands-Ward 5",
    "Scotland/2022/orkney22-W6.blt": "OrkneyIslands-Ward 6",
    "Scotland/2022/orkney22_W1.blt": "OrkneyIslands-Ward 1",
    "Scotland/2022/PreferenceProfile_V0001_North_Isles_Ward_05082022_112827.blt": "ShetlandIslands-North_Isles_Ward",
    "Scotland/2022/PreferenceProfile_V0001_Ward_3___Shetland_West_06052022_120841.blt": "ShetlandIslands-Ward_3 Shetland_West",
    "Scotland/2022/PreferenceProfile_V0001_Ward_4___Shetland_Central_06052022_120841.blt": "ShetlandIslands-Ward_4 Shetland_Central",
    "Scotland/2022/PreferenceProfile_V0001_Ward_5___Lerwick_North_and_Bressay_06052022_120841.blt": "ShetlandIslands-Ward_5 Lerwick_North_and_Bressay",
    "Scotland/2022/PreferenceProfile_V0001_Ward_6___Lerwick_South_06052022_120841.blt": "ShetlandIslands-Ward_6 Lerwick_South",
    "Scotland/2022/PreferenceProfile_V0001_Ward_7___Shetland_South_06052022_120840.blt": "ShetlandIslands-Ward_7 Shetland_South",
    "Scotland/2022/PreferenceProfile_V0001_Ward-1---Troon_06052022_142627.blt": "SouthAyrshire-Ward-1 Troon",
    "Scotland/2022/PreferenceProfile_V0001_Ward-2---Prestwick_06052022_142624.blt": "SouthAyrshire-Ward-2 Prestwick",
    "Scotland/2022/PreferenceProfile_V0001_Ward-4---Ayr-East_06052022_142626.blt": "SouthAyrshire-Ward-4 Ayr-East",
    "Scotland/2022/PreferenceProfile_V0001_Ward-5---Ayr-West_06052022_142628.blt": "SouthAyrshire-Ward-5 Ayr-West",
    "Scotland/2022/PreferenceProfile_V0001_Ward-6---Kyle_06052022_142627.blt": "SouthAyrshire-Ward-6 Kyle",
    "Scotland/2022/PreferenceProfile_V0001_Ward-7---Maybole-North-Carrick-and-Coylton_06052022_142628.blt": "SouthAyrshire-Ward-7 Maybole-North-Carrick-and-Coylton",
    "Scotland/2022/PreferenceProfile_V0001_Ward-8---Girvan-and-South-Carrick_06052022_142628.blt": "SouthAyrshire-Ward-8 Girvan-and-South-Carrick",
    "Scotland/2022/PreferenceProfile_V0009_Ward-3---Ayr-North_10052022_111313.blt": "SouthAyrshire-Ward-3 Ayr-North",
    "Scotland/2022/PreferenceProfile_V0001_Ward_10___East_Kilbride_East.blt": "SouthLanarkshire-Ward_10 East_Kilbride_East",
    "Scotland/2022/PreferenceProfile_V0001_Ward_11___Rutherglen_South.blt": "SouthLanarkshire-Ward_11 Rutherglen_South",
    "Scotland/2022/PreferenceProfile_V0001_Ward_12___Rutherglen_Central_and_North.blt": "SouthLanarkshire-Ward_12 Rutherglen_Central_and_North",
    "Scotland/2022/PreferenceProfile_V0001_Ward_13___Cambuslang_West.blt": "SouthLanarkshire-Ward_13 Cambuslang_West",
    "Scotland/2022/PreferenceProfile_V0001_Ward_14___Cambuslang_East.blt": "SouthLanarkshire-Ward_14 Cambuslang_East",
    "Scotland/2022/PreferenceProfile_V0001_Ward_15___Blantyre.blt": "SouthLanarkshire-Ward_15 Blantyre",
    "Scotland/2022/PreferenceProfile_V0001_Ward_16___Bothwell_and_Uddingston.blt": "SouthLanarkshire-Ward_16 Bothwell_and_Uddingston",
    "Scotland/2022/PreferenceProfile_V0001_Ward_17___Hamilton_North_and_East.blt": "SouthLanarkshire-Ward_17 Hamilton_North_and_East",
    "Scotland/2022/PreferenceProfile_V0001_Ward_18___Hamilton_West_and_Earnock.blt": "SouthLanarkshire-Ward_18 Hamilton_West_and_Earnock",
    "Scotland/2022/PreferenceProfile_V0001_Ward_19___Hamilton_South.blt": "SouthLanarkshire-Ward_19 Hamilton_South",
    "Scotland/2022/PreferenceProfile_V0001_Ward_1___Clydesdale_West.blt": "SouthLanarkshire-Ward_1 Clydesdale_West",
    "Scotland/2022/PreferenceProfile_V0001_Ward_20___Larkhall.blt": "SouthLanarkshire-Ward_20 Larkhall",
    "Scotland/2022/PreferenceProfile_V0001_Ward_2___Clydesdale_North.blt": "SouthLanarkshire-Ward_2 Clydesdale_North",
    "Scotland/2022/PreferenceProfile_V0001_Ward_3___Clydesdale_East.blt": "SouthLanarkshire-Ward_3 Clydesdale_East",
    "Scotland/2022/PreferenceProfile_V0001_Ward_4___Clydesdale_South.blt": "SouthLanarkshire-Ward_4 Clydesdale_South",
    "Scotland/2022/PreferenceProfile_V0001_Ward_5___Avondale_and_Stonehouse.blt": "SouthLanarkshire-Ward_5 Avondale_and_Stonehouse",
    "Scotland/2022/PreferenceProfile_V0001_Ward_6___East_Kilbride_South.blt": "SouthLanarkshire-Ward_6 East_Kilbride_South",
    "Scotland/2022/PreferenceProfile_V0001_Ward_7___East_Kilbride_Central_South.blt": "SouthLanarkshire-Ward_7 East_Kilbride_Central_South",
    "Scotland/2022/PreferenceProfile_V0001_Ward_8___East_Kilbride_Central_North.blt": "SouthLanarkshire-Ward_8 East_Kilbride_Central_North",
    "Scotland/2022/PreferenceProfile_V0001_Ward_9___East_Kilbride_West.blt": "SouthLanarkshire-Ward_9 East_Kilbride_West",
    "Scotland/2022/preferenceprofile_v0001_ward-1-trossachs-and-teith_06052022_124254.blt": "Stirling-ward-1-trossachs-and-teith",
    "Scotland/2022/preferenceprofile_v0001_ward-2-forth-and-endrick_06052022_124253.blt": "Stirling-ward-2-forth-and-endrick",
    "Scotland/2022/preferenceprofile_v0001_ward-3-dunblane-and-bridge-of-allan_06052022_124253.blt": "Stirling-ward-3-dunblane-and-bridge-of-allan",
    "Scotland/2022/preferenceprofile_v0001_ward-4-stirling-north_06052022_124253.blt": "Stirling-ward-4-stirling-north",
    "Scotland/2022/preferenceprofile_v0001_ward-5-stirling-west_06052022_124253.blt": "Stirling-ward-5-stirling-west",
    "Scotland/2022/preferenceprofile_v0001_ward-6-stirling-east_06052022_124253.blt": "Stirling-ward-6-stirling-east",
    "Scotland/2022/preferenceprofile_v0001_ward-7-bannockburn_06052022_124254.blt": "Stirling-ward-7-bannockburn",
    "Scotland/2022/preferenceprofile_v0001_ward-1-lomond_06052022_120102.blt": "WestDunbartonshire-ward-1-lomond",
    "Scotland/2022/preferenceprofile_v0001_ward-2-leven_06052022_120059.blt": "WestDunbartonshire-ward-2-leven",
    "Scotland/2022/preferenceprofile_v0001_ward-3-dumbarton_06052022_120059.blt": "WestDunbartonshire-ward-3-dumbarton",
    "Scotland/2022/preferenceprofile_v0001_ward-4-kilpatrick_06052022_120059.blt": "WestDunbartonshire-ward-4-kilpatrick",
    "Scotland/2022/preferenceprofile_v0001_ward-5-clydebank-central_06052022_120100.blt": "WestDunbartonshire-ward-5-clydebank-central",
    "Scotland/2022/preferenceprofile_v0001_ward-6-clydebank-waterfront_06052022_120103.blt": "WestDunbartonshire-ward-6-clydebank-waterfront",
    # AUSTRALIA 2016, 2019, 2022
    "FedAus16/FederalSenate2016ACT.json": "ACT 16",
    "FedAus16/FederalSenate2016NSW.json": "NSW 16",
    "FedAus16/FederalSenate2016NT.json": "NT 16",
    "FedAus16/FederalSenate2016QLD.json": "QLD 16",
    "FedAus16/FederalSenate2016SA.json": "SA 16",
    "FedAus16/FederalSenate2016TAS.json": "TAS 16",
    "FedAus16/FederalSenate2016VIC.json": "VIC 16",
    "FedAus16/FederalSenate2016WA.json": "WA 16",
    "FedAus19/FederalSenate2019ACT.json": "ACT 19",
    "FedAus19/FederalSenate2019NSW.json": "NSW 19",
    "FedAus19/FederalSenate2019NT.json": "NT 19",
    "FedAus19/FederalSenate2019QLD.json": "QLD 19",
    "FedAus19/FederalSenate2019SA.json": "SA 19",
    "FedAus19/FederalSenate2019TAS.json": "TAS 19",
    "FedAus19/FederalSenate2019VIC.json": "VIC 19",
    "FedAus19/FederalSenate2019WA.json": "WA 19",
    "FedAus22/2022ACT.json": "ACT 22",
    "FedAus22/FederalSenate2022NSW.json": "NSW 22",
    "FedAus22/2022NT.json": "NT 22",
    "FedAus22/FederalSenate2022QLD.json": "QLD 22",
    "FedAus22/FederalSenate2022SA.json": "SA 22",
    "FedAus22/FederalSenate2022TAS.json": "TAS 22",
    "FedAus22/FederalSenate2022VIC.json": "VIC 22",
    "FedAus22/FederalSenate2022WA.json": "WA 22",
    # Minneapolis
    "Minneapolis/MPLS-2009-BET_2Seat_ParsedMB.txt": "Minneapolis BET 09",
    "Minneapolis/MPLS-2013-BET_2Seat_ParsedMB.txt": "Minneapolis BET 13",
    "Minneapolis/MPLS-2017-BET_2Seat_ParsedMB.txt": "Minneapolis BET 17",
    "Minneapolis/MPLS-2021-BET_2Seat_ParsedMB.txt": "Minneapolis BET 21",
    "example.txt": "Example",
    "example1.txt": "Example1",
    "data_election_temp_example.json": "SouthAyrshire-Ward-7 Maybole-North-Carrick-and-Coylton CHANGED"
}

datafiles = [
    # AUSTRALIA 2-seat, 2016, 2019, 2022
    ("FedAus16/FederalSenate2016ACT.json", 2),
    ("FedAus16/FederalSenate2016NT.json", 2),
    # ("FedAus16/FederalSenate2016NSW.json", 12),
    # ("FedAus16/FederalSenate2016QLD.json", 12),
    # ("FedAus16/FederalSenate2016SA.json", 12),
    # ("FedAus16/FederalSenate2016TAS.json", 12),
    # ("FedAus16/FederalSenate2016VIC.json", 12),
    # ("FedAus16/FederalSenate2016WA.json", 12),
    ("FedAus19/FederalSenate2019ACT.json", 2),
    ("FedAus19/FederalSenate2019NT.json", 2),
    # ("FedAus19/FederalSenate2019NSW.json", 6),
    # ("FedAus19/FederalSenate2019QLD.json", 6),
    # ("FedAus19/FederalSenate2019SA.json", 6),
    # ("FedAus19/FederalSenate2019TAS.json", 6),
    # ("FedAus19/FederalSenate2019VIC.json", 6),
    # ("FedAus19/FederalSenate2019WA.json", 6),
    ("FedAus22/2022ACT.json", 2),
    ("FedAus22/2022NT.json", 2),
    # ("FedAus22/FederalSenate2022NSW.json", 6),
    # ("FedAus22/FederalSenate2022QLD.json", 6),
    # ("FedAus22/FederalSenate2022SA.json", 6),
    # ("FedAus22/FederalSenate2022TAS.json", 6),
    # ("FedAus22/FederalSenate2022VIC.json", 6),
    # ("FedAus22/FederalSenate2022WA.json", 6),
    # GLASGOW, SCOTLAND 2007
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
    # IRELAND 2002
    ("Ireland/DublinNorth2002_ballots.txt", 4), ("Ireland/DublinWest2002_ballots.txt", 3),
    ("Ireland/Meath2002_ballots.txt", 5),
    # MIXED, SCOTLAND 2022, CANDIDATES > 10?
    ("Scotland/2022/PreferenceProfile_V0001_Ward_11___City_Centre_06052022_155600.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_12___Leith_Walk_06052022_160625.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-3-Greater-Pollok_06052022_163750.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-18-East-Centre_06052022_165259.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-5-Govan_06052022_165258.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-19-mearns_06052022_172124.blt", 4),
    ("Scotland/2022/preferenceprofile_v0004_ward-4-oban-south-and-the-isles_06052022_143143.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_5___Inverleith_06052022_155559.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_16___Liberton_Gilmerton_06052022_160625.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-6-Pollokshields_06052022_170301.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-4-Dunfermline-South_06052022_151924.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-8-Southside-Central_06052022_165258.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-2-Newlands-Auldburn_06052022_165250.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-14-Drumchapel-Anniesland_06052022_170258.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-3-dunblane-and-bridge-of-allan_06052022_124253.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-6---Arbroath-West-Letham-and-Friockheim_06052022_150511.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-1-West-Fife-and-Coastal-Villages_06052022_145537.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-10-Anderston-City-Yorkhill_06052022_170256.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-16-Canal_06052022_163755.blt", 4),
    # More Scotland 2022, CANDIDATES = 8 to 10
    ("Scotland/2022/PreferenceProfile_V0001_Ward-15-Glenrothes-Central-and-Thornton_06052022_145551.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-6-stirling-east_06052022_124253.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-3---West-End_06052022_161516.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-8---The-Ferry_06052022_161517.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_17___Portobello_Craigmillar_06052022_155600.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-1-Linn_06052022_163754.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_7___East_Kilbride_Central_South.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-7-Cowdenbeath_06052022_145532.blt", 4),
    ("Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_1___Musselburgh_06052022_153935.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0009_Ward-3---Ayr-North_10052022_111313.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-3---Forfar-and-District_06052022_150515.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_14___Cambuslang_East.blt", 3),
    ("Scotland/2022/PreferenceProfile_Ward-4.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-5-peterhead-north-and-rattray_06052022_172118.blt", 4),
    ("Scotland/2022/preferenceprofile_v0009_ward-8-isle-of-bute_06052022_165355.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_4___Forth_06052022_160611.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-2-Dunfermline-North_06052022_151927.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-1---Strathmartine_06052022_161516.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-3-Dunfermline-Central_06052022_145551.blt", 4),
    ("Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_4___North_Berwick_Coastal_06052022_153938.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-19-Shettleston_06052022_170301.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_3___Shetland_West_06052022_120841.blt", 2),
    ("Scotland/2022/PreferenceProfile_V0001_Black_Isle_06052022_161539.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-1---Troon_06052022_142627.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-4-central-buchan_06052022_172124.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-10-Kirkcaldy-North_06052022_151928.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-15-Maryhill_06052022_165258.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-2---Lochee_06052022_161513.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-4-Cardonald_06052022_163754.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Torry-Ferryhill-Ward_06052022_160545.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-4---Monifieth-and-Sidlaw_06052022_150515.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Inverness_West_06052022_161539.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-19-East-Neuk-and-Landward_06052022_145551.blt", 3),
    ("Scotland/2022/cnesair_ward09_preferenceprofile.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-14-Glenrothes-North-Leslie-and-Markinch_06052022_151925.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Tillydrone-Seaton-Old-Aberdeen-Ward_06052022_160546.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-3-dumbarton_06052022_120059.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_9___East_Kilbride_West.blt", 3),
    ("Scotland/2022/falkirk22_Preference Profile_w9.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-5---Maryfield_06052022_161515.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-20-Cupar_06052022_151928.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-7-Langside_06052022_165250.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_3___Clydesdale_East.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-2-leven_06052022_120059.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-8---Montrose-and-District_06052022_150515.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-4---Ayr-East_06052022_142626.blt", 3),
    ("Scotland/2022/orkney22-W2.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Northfield-Mastrick-North-Ward_06052022_160545.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Badenoch_and_Strathspey_06052022_161540.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Nairn_and_Cawdor_06052022_161539.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Bridge-of-Don-Ward_06052022_160546.blt", 4),
    ("Scotland/2022/Ward_6_Midlothian_South_Dalkeith_preference_profile__open_from_within_MS_Word_or_similar_.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-17-Tay-Bridgehead_06052022_145551.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-5-Rosyth_06052022_145544.blt", 3),
    ("Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_5___Haddington_and_Lammermuir_06052022_153938.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-17-Springburn-Robroyston_06052022_170301.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-21-Leven-Kennoway-and-Largo_06052022_145552.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Cromarty_Firth_06052022_161538.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-7-bannockburn_06052022_124254.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-10-west-garioch_06052022_172124.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-5---Ayr-West_06052022_142628.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-18-stonehaven-and-lower-deeside_06052022_172124.blt", 4),
    ("Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_3___Tranent_Wallyford_and_Macmerry_06052022_153937.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-4---Coldside_06052022_161514.blt", 4),
    ("Scotland/2022/falkirk22_Preference Profile_W2.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Inverness_Central_06052022_161539.blt", 3),
    ("Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_2___Preston_Seton_and_Gosford_06052022_153931.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-2---Prestwick_06052022_142624.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-9-Calton_06052022_163749.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_13___Leith_06052022_155600.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-1-trossachs-and-teith_06052022_124254.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Dyce-Bucksburn-Danestone-Ward_06052022_160545.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_2___Pentland_Hills_06052022_160611.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-9-Burntisland-Kinghorn-and-Western-Kirkcaldy_06052022_145551.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-1-banff-and-district_06052022_172114.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-23-Partick-East-Kelvindale_06052022_170257.blt", 4),
    ("Scotland/2022/preferenceprofile_v0003_ward-3-mid-argyll_06052022_133803.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_6___East_Kilbride_South.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-6-Inverkeithing-and-Dalgety-Bay_06052022_151927.blt", 4),
    ("Scotland/2022/cnesair_ward02_preferenceprofile.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Kincorth-Nigg-Cove-Ward_06052022_160546.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-2-forth-and-endrick_06052022_124253.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_7___Sighthill_Gorgie_06052022_155557.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-21-North-East_06052022_170301.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Eilean_a__Che___06052022_161539.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-22-Buckhaven-Methil-and-Wemyss-Villages_06052022_151928.blt", 4),
    ("Scotland/2022/clacks_W2_North_2022_6694.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-4---Castle-Douglas-and-Crocketford_06052022_171202.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_20___Larkhall.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-12-Kirkcaldy-East_06052022_151925.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_3___Drum_Brae_Gyle_06052022_155559.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_1___Almond_06052022_155516.blt", 4),
    ("Scotland/2022/preferenceprofile_v0005_ward-5-oban-north-and-lorn_06052022_151453.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-17-north-kincardine_06052022_172124.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-8-Lochgelly-Cardenden-and-Benarty_06052022_151928.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_4___Clydesdale_South.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-13-Garscadden-Scotstounhill_06052022_165250.blt", 4),
    # EVEN MORE SCOTLAND 2022, CANDIDATES less than 8
    ("Scotland/2022/PreferenceProfile_Ward-3.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_2___Bonnyrigg_06052022_151836.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-5---Carnoustie-and-District_06052022_150514(1).blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-1---Stranraer-and-the-Rhins_06052022_171141.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-11-inverurie-and-district_06052022_172124.blt", 4),
    ("Scotland/2022/cnesair_ward07_preferenceprofile.blt", 3),
    ("Scotland/2022/PreferenceProfile_Ward-2.blt", 3),
    ("Scotland/2022/cnesair_ward_05_preferenceprofile.blt", 2),
    ("Scotland/2022/PreferenceProfile_V0001_Culloden_and_Ardersier_06052022_161539.blt", 3),
    ("Scotland/2022/Ward_1_Penicuik_preference_profile__open_from_within_MS_Word_or_similar_.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_6___Lerwick_South_06052022_120841.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-3-fraserburgh-and-district_06052022_172124.blt", 4),
    ("Scotland/2022/preferenceprofile_v0007_ward-6-cowal_06052022_160055.blt", 3),
    ("Scotland/2022/PreferenceProfile_Ward-5.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_5___Lerwick_North_and_Bressay_06052022_120841.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-6---Kyle_06052022_142627.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-1-south-kintyre_06052022_120128.blt", 3),
    ("Scotland/2022/orkney22_W1.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_North_West_and_Central_Sutherland_06052022_161534.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-16-Howe-Of-Fife-and-Tay-Coast_06052022_151928.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Lower-Deeside-Ward_06052022_160546.blt", 3),
    ("Scotland/2022/preferenceprofile_v0012_ward-11-helensburgh-and-lomond-south_06052022_182005.blt", 3),
    ("Scotland/2022/PreferenceProfile_Ward-6.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-12-east-garioch_06052022_172124.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-4-kilpatrick_06052022_120059.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-8---Girvan-and-South-Carrick_06052022_142628.blt", 3),
    ("Scotland/2022/PreferenceProfile_Ward-7.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-8-mid-formartine_06052022_172123.blt", 4),
    ("Scotland/2022/preferenceprofile_v0008_ward-7-dunoon_06052022_163322.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-4-stirling-north_06052022_124253.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-2---Brechin-and-Edzell_06052022_150515.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Hilton-Woodside-Stockethill-Ward_06052022_160546.blt", 3),
    ("Scotland/2022/clacks_W1_West_2022_6693.blt", 4),
    ("Scotland/2022/moray22_ward8.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_18___Hamilton_West_and_Earnock.blt", 4),
    ("Scotland/2022/elothian22_PreferenceProfile_V0001_Ward_6___Dunbar_and_East_Linton_06052022_153938.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_5___Avondale_and_Stonehouse.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Inverness_South_06052022_161540.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_9___Fountainbridge_Craiglockhart_06052022_155600.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-11---Annandale-North_06052022_171202.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-9-ellon-and-district_06052022_172124.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-20-Baillieston_06052022_170301.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Fort_William_and_Ardnamurchan_06052022_161540.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_14___Craigentinny_Duddingston_06052022_160625.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-14-huntly-strathbogie-and-howe-of-alford_06052022_172124.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Aird_and_Loch_Ness_06052022_161539.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Thurso_and_Northwest_Caithness_06052022_161528.blt", 4),
    ("Scotland/2022/cnesair_ward_03_preferenceprofile.blt", 2),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-12---Annandale-East-and-Eskdale_06052022_171202.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_8___East_Kilbride_Central_North.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Kingswells-Sheddocksley-Summerhill-Ward_06052022_160546.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-6---North-West-Dumfries_06052022_171201.blt", 4),
    ("Scotland/2022/Ward_4_Midlothian_West_preference_profile__open_from_within_MS_Word_or_similar_.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_4___Shetland_Central_06052022_120841.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-5---Abbey_06052022_171201.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Hazlehead-Queens-Cross-Countesswells-Ward_06052022_160545.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-1-lomond_06052022_120102.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-13-Glenrothes-West-and-Kinglassie_06052022_145551.blt", 3),
    ("Scotland/2022/falkirk22_Preference Profile_w8.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_17___Hamilton_North_and_East.blt", 3),
    ("Scotland/2022/Ward_5_Midlothian_East_preference_profile__open_from_within_MS_Word_or_similar_.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_10___East_Kilbride_East.blt", 3),
    ("Scotland/2022/cnesair_ward_04_preferenceprofile.blt", 2),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_10___Morningside_06052022_160625.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_East_Sutherland_and_Edderton_06052022_161530.blt", 3),
    ("Scotland/2022/falkirk22_Preference Profile_W5.blt", 3),
    ("Scotland/2022/moray22_ward1.blt", 3),
    ("Scotland/2022/falkirk22_Preference Profile_W4.blt", 4),
    ("Scotland/2022/orkney22-W3.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-11-Kirkcaldy-Central_06052022_145551.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-1---Kirriemuir-and-Dean_06052022_150515(1).blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_15___Southside_Newington_06052022_155603.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Wester_Ross_Strathpeffer_and_Lochalsh_06052022_161539.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-18-St-Andrews_06052022_151928.blt", 4),
    ("Scotland/2022/falkirk22_Preference Profile_w6.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-7-turriff-and-district_06052022_172118.blt", 4),
    ("Scotland/2022/falkirk22_Preference Profile_w7.blt", 3),
    ("Scotland/2022/moray22_ward2.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-7---Arbroath-East-and-Lunan_06052022_150515.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-6-peterhead-south-and-cruden_06052022_172115.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Inverness_Millburn_06052022_161539.blt", 3),
    ("Scotland/2022/cnesair_ward10_preferenceprofile.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-7---Mid-and-Upper-Nithsdale_06052022_171202.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-6---North-East_06052022_161516.blt", 3),
    ("Scotland/2022/orkney22-W4.blt", 4),
    ("Scotland/2022/moray22_ward6.blt", 3),
    ("Scotland/2022/falkirk22_Preference Profile_W3.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-11-Hillhead_06052022_163755.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_13___Cambuslang_West.blt", 3),
    ("Scotland/2022/moray22_ward7.blt", 3),
    ("Scotland/2022/orkney22-W5.blt", 3),
    ("Scotland/2022/clacks_W3_Central_2022_6695.blt", 3),
    ("Scotland/2022/clacks_W4_South_2022_6696.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_7___Shetland_South_06052022_120840.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-13-westhill-and-district_06052022_172124.blt", 4),
    ("Scotland/2022/preferenceprofile_v0010_ward-9-lomond-north_06052022_173349.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-15-aboyne-upper-deeside-and-donside_06052022_172124.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-2---Mid-Galloway-and-Wigtown-West_06052022_171201.blt", 4),
    ("Scotland/2022/moray22_ward5.blt", 4),
    ("Scotland/2022/moray22_ward4.blt", 3),
    ("Scotland/2022/falkirk22_Preference Profile_W1.blt", 3),
    ("Scotland/2022/orkney22-W6.blt", 3),
    ("Scotland/2022/preferenceprofile_v0012_ward-10-helensburgh-central_06052022_182005.blt", 4),
    ("Scotland/2022/Ward_3_Dalkeith_preference_profile__open_from_within_MS_Word_or_similar_.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-5-clydebank-central_06052022_120100.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_George-St-Harbour-Ward_06052022_160545.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_1___Clydesdale_West.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-9---Nith_06052022_171202.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-6-clydebank-waterfront_06052022_120103.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_2___Clydesdale_North.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_16___Bothwell_and_Uddingston.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_North_Isles_Ward_05082022_112827.blt", 1),
    ("Scotland/2022/PreferenceProfile_V0001_Midstocket-Rosemount-Ward_06052022_160545.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Wick_and_East_Caithness_06052022_161532.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_19___Hamilton_South.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-12-Victoria-Park_06052022_163755.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_15___Blantyre.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-7---Maybole-North-Carrick-and-Coylton_06052022_142628.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Dingwall_and_Seaforth_06052022_161539.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_11___Rutherglen_South.blt", 3),
    ("Scotland/2022/preferenceprofile_v0002_ward-2-kintyre-and-the-islands_06052022_130502.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-10---Annandale-South_06052022_171202.blt", 4),
    ("Scotland/2022/preferenceprofile_v0001_ward-2-troup_06052022_172123.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_6___Corstorphine_Murrayfield_06052022_160625.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-22-Dennistoun_06052022_163757.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Tain_and_Easter_Ross_06052022_161537.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-7---East-End_06052022_161516.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_12___Rutherglen_Central_and_North.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward_8___Colinton_Fairmilehead_06052022_160625.blt", 3),
    ("Scotland/2022/clacks_W5_East_2022_6697.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-16-banchory-and-mid-deeside_06052022_172124.blt", 3),
    ("Scotland/2022/cnesair_ward08_preferenceprofile.blt", 3),
    ("Scotland/2022/preferenceprofile_v0001_ward-5-stirling-west_06052022_124253.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Inverness_Ness_side_06052022_161539.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Airyhall-Broomhill-Garthdee-Ward_06052022_160546.blt", 3),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-8---Lochar_06052022_171202.blt", 4),
    ("Scotland/2022/PreferenceProfile_V0001_Ward-3---Dee-and-Glenkens_06052022_171147.blt", 3),
    # Minneapolis
    ("Minneapolis/MPLS-2009-BET_2Seat_ParsedMB.txt", 2),
    ("Minneapolis/MPLS-2013-BET_2Seat_ParsedMB.txt", 2),
    ("Minneapolis/MPLS-2017-BET_2Seat_ParsedMB.txt", 2),
    ("Minneapolis/MPLS-2021-BET_2Seat_ParsedMB.txt", 2),
]

ubs = {
    "ACT 16": 18835,
    "NT 16": 11244,
    "ACT 19": 12939,
    "NT 19": 15890,
    "ACT 22": 11078,
    "NT 22": 11412,
    "Anderston/City 07": 99,
    "Baillieston 07": 105,
    "Calton 07": 376,
    "Canal 07": 126,
    "Craigton 07": 75,
    "Drumchapel/Anniesland 07": 443,
    "East Centre 07": 139,
    "Garscadden/Scotstounhill 07": 396,
    "Govan 07": 309,
    "Greater Pollok 07": 237,
    "Hillhead 07": 105,
    "Langside 07": 233,
    "Linn 07": 218,
    "Maryhill/Kelvin 07": 321,
    "Newlands/Auldburn 07": 88,
    "North East 07": 421,
    "Partick West 07": 193,
    "Pollokshields 07": 3,
    "Shettleston 07": 353,
    "Southside Central 07": 229,
    "Springburn 07": 528,
    "Dublin North": 211,
    "Dublin West": 366,
    "Meath": 1113,
    "Edinburgh-Ward_11 City_Centre": 10,
    "Edinburgh-Ward_12 Leith_Walk": 174,
    "Glasgow-Ward-3-Greater-Pollok": 437,
    "Glasgow-Ward-18-East-Centre": 255,
    "Glasgow-Ward-5-Govan": 73,
    "Aberdeenshire-ward-19-mearns": 18,
    "ArgyllAndBute-ward-4-oban-south-and-the-isles": 1,
    "Edinburgh-Ward_5 Inverleith": 1,
    "Edinburgh-Ward_16 Liberton_Gilmerton": 63,
    "Glasgow-Ward-6-Pollokshields": 89,
    "Fife-Ward-4-Dunfermline-South": 264,
    "Glasgow-Ward-8-Southside-Central": 27,
    "Glasgow-Ward-2-Newlands-Auldburn": 20,
    "Glasgow-Ward-14-Drumchapel-Anniesland": 327,
    "Stirling-ward-3-dunblane-and-bridge-of-allan": 51,
    "Angus-Ward-6 Arbroath-West-Letham-and-Friockheim": 2,
    "Fife-Ward-1-West-Fife-and-Coastal-Villages": 130,
    "Glasgow-Ward-10-Anderston-City-Yorkhill": 59,
    "Glasgow-Ward-16-Canal": 107,
    "Fife-Ward-15-Glenrothes-Central-and-Thornton": 271,
    "Stirling-ward-6-stirling-east": 175,
    "DumfriesAndGalloway-Ward-3 West-End": 87,
    "DumfriesAndGalloway-Ward-8 The-Ferry": 210,
    "Edinburgh-Ward_17 Portobello_Craigmillar": 111,
    "Glasgow-Ward-1-Linn": 111,
    "SouthLanarkshire-Ward_7 East_Kilbride_Central_South": 62,
    "Fife-Ward-7-Cowdenbeath": 3,
    "EastLothian-Ward_1 Musselburgh": 13,
    "SouthAyrshire-Ward-3 Ayr-North": 203,
    "Angus-Ward-3 Forfar-and-District": 125,
    "SouthLanarkshire-Ward_14 Cambuslang_East": 63,
    "Inverclyde-Ward-4": 19,
    "Aberdeenshire-ward-5-peterhead-north-and-rattray": 38,
    "ArgyllAndBute-ward-8-isle-of-bute": 1,
    "Edinburgh-Ward_4 Forth": 11,
    "Fife-Ward-2-Dunfermline-North": 73,
    "DumfriesAndGalloway-Ward-1 Strathmartine": 532,
    "Fife-Ward-3-Dunfermline-Central": 95,
    "EastLothian-Ward_4 North_Berwick_Coastal": 52,
    "Glasgow-Ward-19-Shettleston": 21,
    "ShetlandIslands-Ward_3 Shetland_West": 4,
    "Highland-Black_Isle": 123,
    "SouthAyrshire-Ward-1 Troon": 71,
    "Aberdeenshire-ward-4-central-buchan": 6,
    "Fife-Ward-10-Kirkcaldy-North": 46,
    "Glasgow-Ward-15-Maryhill": 130,
    "DumfriesAndGalloway-Ward-2 Lochee": 231,
    "Glasgow-Ward-4-Cardonald": 496,
    "Aberdeen-Torry-Ferryhill": 186,
    "Angus-Ward-4 Monifieth-and-Sidlaw": 25,
    "Highland-Inverness_West": 1,
    "Fife-Ward-19-East-Neuk-and-Landward": 289,
    "Comhairle nan Eilean Siar-Ward 09": 43,
    "Fife-Ward-14-Glenrothes-North-Leslie-and-Markinch": 101,
    "Aberdeen-Tillydrone-Seaton-Old-Aberdeen": 85,
    "WestDunbartonshire-ward-3-dumbarton": 322,
    "SouthLanarkshire-Ward_9 East_Kilbride_West": 3,
    "Falkirk-Ward 9": 270,
    "DumfriesAndGalloway-Ward-5 Maryfield": 231,
    "Fife-Ward-20-Cupar": 500,
    "Glasgow-Ward-7-Langside": 30,
    "SouthLanarkshire-Ward_3 Clydesdale_East": 145,
    "WestDunbartonshire-ward-2-leven": 57,
    "Angus-Ward-8 Montrose-and-District": 87,
    "SouthAyrshire-Ward-4 Ayr-East": 159,
    "OrkneyIslands-Ward 2": 10,
    "Aberdeen-Northfield-Mastrick-North": 335,
    "Highland-Badenoch_and_Strathspey": 97,
    "Highland-Nairn_and_Cawdor": 66,
    "Aberdeen-Bridge-of-Don": 107,
    "Midlothian-Ward_6_Midlothian_South_Dalkeith": 49,
    "Fife-Ward-17-Tay-Bridgehead": 659,
    "Fife-Ward-5-Rosyth": 13,
    "EastLothian-Ward_5 Haddington_and_Lammermuir": 105,
    "Glasgow-Ward-17-Springburn-Robroyston": 424,
    "Fife-Ward-21-Leven-Kennoway-and-Largo": 362,
    "Highland-Cromarty_Firth": 72,
    "Stirling-ward-7-bannockburn": 79,
    "Aberdeenshire-ward-10-west-garioch": 92,
    "SouthAyrshire-Ward-5 Ayr-West": 203,
    "Aberdeenshire-ward-18-stonehaven-and-lower-deeside": 7,
    "EastLothian-Ward_3 Tranent_Wallyford_and_Macmerry": 34,
    "DumfriesAndGalloway-Ward-4 Coldside": 78,
    "Falkirk-Ward 2": 5,
    "Highland-Inverness_Central": 140,
    "EastLothian-Ward_2 Preston_Seton_and_Gosford": 184,
    "SouthAyrshire-Ward-2 Prestwick": 90,
    "Glasgow-Ward-9-Calton": 71,
    "Edinburgh-Ward_13 Leith": 814,
    "Stirling-ward-1-trossachs-and-teith": 53,
    "Aberdeen-Dyce-Bucksburn-Danestone": 280,
    "Edinburgh-Ward_2 Pentland_Hills": 7,
    "Fife-Ward-9-Burntisland-Kinghorn-and-Western-Kirkcaldy": 213,
    "Aberdeenshire-ward-1-banff-and-district": 268,
    "Glasgow-Ward-23-Partick-East-Kelvindale": 60,
    "ArgyllAndBute-ward-3-mid-argyll": 3,
    "SouthLanarkshire-Ward_6 East_Kilbride_South": 97,
    "Fife-Ward-6-Inverkeithing-and-Dalgety-Bay": 216,
    "Comhairle nan Eilean Siar-Ward 02": 24,
    "Aberdeen-Kincorth-Nigg-Cove": 285,
    "Stirling-ward-2-forth-and-endrick": 58,
    "Edinburgh-Ward_7 Sighthill_Gorgie": 129,
    "Glasgow-Ward-21-North-East": 103,
    "Highland-Eilean_a__Che": 8,
    "Fife-Ward-22-Buckhaven-Methil-and-Wemyss-Villages": 413,
    "Clackmannanshire-Ward 2_North_2022_6694": 260,
    "DumfriesAndGalloway-Ward-4 Castle-Douglas-and-Crocketford": 21,
    "SouthLanarkshire-Ward_20 Larkhall": 45,
    "Fife-Ward-12-Kirkcaldy-East": 10,
    "Edinburgh-Ward_3 Drum_Brae_Gyle": 596,
    "Edinburgh-Ward_1 Almond": 728,
    "ArgyllAndBute-ward-5-oban-north-and-lorn": 75,
    "Aberdeenshire-ward-17-north-kincardine": 125,
    "Fife-Ward-8-Lochgelly-Cardenden-and-Benarty": 401,
    "SouthLanarkshire-Ward_4 Clydesdale_South": 67,
    "Glasgow-Ward-13-Garscadden-Scotstounhill": 8,
    "Inverclyde-Ward-3": 134,
    "Midlothian-Ward_2 Bonnyrigg": 85,
    "Angus-Ward-5 Carnoustie-and-District": 80,
    "DumfriesAndGalloway-Ward-1 Stranraer-and-the-Rhins": 101,
    "Aberdeenshire-ward-11-inverurie-and-district": 277,
    "Comhairle nan Eilean Siar-Ward 07": 28,
    "Inverclyde-Ward-2": 40,
    "Comhairle nan Eilean Siar-Ward 05": 112,
    "Highland-Culloden_and_Ardersier": 64,
    "Midlothian-Ward_1_Penicuik": 44,
    "ShetlandIslands-Ward_6 Lerwick_South": 37,
    "Aberdeenshire-ward-3-fraserburgh-and-district": 49,
    "ArgyllAndBute-ward-6-cowal": 131,
    "Inverclyde-Ward-5": 493,
    "ShetlandIslands-Ward_5 Lerwick_North_and_Bressay": 24,
    "SouthAyrshire-Ward-6 Kyle": 97,
    "ArgyllAndBute-ward-1-south-kintyre": 115,
    "OrkneyIslands-Ward 1": 138,
    "Highland-North_West_and_Central_Sutherland": 166,
    "Fife-Ward-16-Howe-Of-Fife-and-Tay-Coast": 326,
    "Aberdeen-Lower-Deeside": 165,
    "ArgyllAndBute-ward-11-helensburgh-and-lomond-south": 27,
    "Inverclyde-Ward-6": 100,
    "Aberdeenshire-ward-12-east-garioch": 13,
    "WestDunbartonshire-ward-4-kilpatrick": 278,
    "SouthAyrshire-Ward-8 Girvan-and-South-Carrick": 10,
    "Inverclyde-Ward-7": 194,
    "Aberdeenshire-ward-8-mid-formartine": 12,
    "ArgyllAndBute-ward-7-dunoon": 35,
    "Stirling-ward-4-stirling-north": 29,
    "Angus-Ward-2 Brechin-and-Edzell": 312,
    "Aberdeen-Hilton-Woodside-Stockethill": 48,
    "Clackmannanshire-Ward 1_West_2022_6693": 299,
    "Moray-Ward 8": 24,
    "SouthLanarkshire-Ward_18 Hamilton_West_and_Earnock": 64,
    "EastLothian-Ward_6 Dunbar_and_East_Linton": 140,
    "SouthLanarkshire-Ward_5 Avondale_and_Stonehouse": 79,
    "Highland-Inverness_South": 14,
    "Edinburgh-Ward_9 Fountainbridge_Craiglockhart": 60,
    "DumfriesAndGalloway-Ward-11 Annandale-North": 243,
    "Aberdeenshire-ward-9-ellon-and-district": 78,
    "Glasgow-Ward-20-Baillieston": 63,
    "Highland-Fort_William_and_Ardnamurchan": 77,
    "Edinburgh-Ward_14 Craigentinny_Duddingston": 60,
    "Aberdeenshire-ward-14-huntly-strathbogie-and-howe-of-alford": 180,
    "Highland-Aird_and_Loch_Ness": 76,
    "Highland-Thurso_and_Northwest_Caithness": 94,
    "Comhairle nan Eilean Siar-Ward 03": 74,
    "DumfriesAndGalloway-Ward-12 Annandale-East-and-Eskdale": 14,
    "SouthLanarkshire-Ward_8 East_Kilbride_Central_North": 69,
    "Aberdeen-Kingswells-Sheddocksley-Summerhill": 138,
    "DumfriesAndGalloway-Ward-6 North-West-Dumfries": 15,
    "Midlothian-Ward_4_Midlothian_West": 9,
    "ShetlandIslands-Ward_4 Shetland_Central": 111,
    "DumfriesAndGalloway-Ward-5 Abbey": 270,
    "Aberdeen-Hazlehead-Queens-Cross-Countesswells": 70,
    "WestDunbartonshire-ward-1-lomond": 89,
    "Fife-Ward-13-Glenrothes-West-and-Kinglassie": 221,
    "Falkirk-Ward 8": 157,
    "SouthLanarkshire-Ward_17 Hamilton_North_and_East": 117,
    "Midlothian-Ward_5_Midlothian_East": 223,
    "SouthLanarkshire-Ward_10 East_Kilbride_East": 65,
    "Comhairle nan Eilean Siar-Ward 04": 65,
    "Edinburgh-Ward_10 Morningside": 94,
    "Highland-East_Sutherland_and_Edderton": 100,
    "Falkirk-Ward 5": 122,
    "Moray-Ward 1": 199,
    "Falkirk-Ward 4": 253,
    "OrkneyIslands-Ward 3": 21,
    "Fife-Ward-11-Kirkcaldy-Central": 128,
    "Angus-Ward-1 Kirriemuir-and-Dean": 64,
    "Edinburgh-Ward_15 Southside_Newington": 89,
    "Highland-Wester_Ross_Strathpeffer_and_Lochalsh": 36,
    "Fife-Ward-18-St-Andrews": 10,
    "Falkirk-Ward 6": 10,
    "Aberdeenshire-ward-7-turriff-and-district": 23,
    "Falkirk-Ward 7": 239,
    "Moray-Ward 2": 30,
    "Angus-Ward-7 Arbroath-East-and-Lunan": 46,
    "Aberdeenshire-ward-6-peterhead-south-and-cruden": 101,
    "Highland-Inverness_Millburn": 49,
    "Comhairle nan Eilean Siar-Ward 10": 20,
    "DumfriesAndGalloway-Ward-7 Mid-and-Upper-Nithsdale": 9,
    "DumfriesAndGalloway-Ward-6 North-East": 494,
    "OrkneyIslands-Ward 4": 54,
    "Moray-Ward 6": 347,
    "Falkirk-Ward 3": 8,
    "Glasgow-Ward-11-Hillhead": 713,
    "SouthLanarkshire-Ward_13 Cambuslang_West": 48,
    "Moray-Ward 7": 387,
    "OrkneyIslands-Ward 5": 15,
    "Clackmannanshire-Ward 3_Central_2022_6695": 22,
    "Clackmannanshire-Ward 4_South_2022_6696": 30,
    "ShetlandIslands-Ward_7 Shetland_South": 82,
    "Aberdeenshire-ward-13-westhill-and-district": 196,
    "ArgyllAndBute-ward-9-lomond-north": 4,
    "Aberdeenshire-ward-15-aboyne-upper-deeside-and-donside": 14,
    "DumfriesAndGalloway-Ward-2 Mid-Galloway-and-Wigtown-West": 36,
    "Moray-Ward 5": 111,
    "Moray-Ward 4": 8,
    "Falkirk-Ward 1": 202,
    "OrkneyIslands-Ward 6": 93,
    "ArgyllAndBute-ward-10-helensburgh-central": 36,
    "Midlothian-Ward_3_Dalkeith": 261,
    "WestDunbartonshire-ward-5-clydebank-central": 374,
    "Aberdeen-George-St-Harbour": 16,
    "SouthLanarkshire-Ward_1 Clydesdale_West": 235,
    "DumfriesAndGalloway-Ward-9 Nith": 42,
    "WestDunbartonshire-ward-6-clydebank-waterfront": 281,
    "SouthLanarkshire-Ward_2 Clydesdale_North": 547,
    "SouthLanarkshire-Ward_16 Bothwell_and_Uddingston": 53,
    "ShetlandIslands-North_Isles_Ward": 305,
    "Aberdeen-Midstocket-Rosemount": 218,
    "Highland-Wick_and_East_Caithness": 43,
    "SouthLanarkshire-Ward_19 Hamilton_South": 265,
    "Glasgow-Ward-12-Victoria-Park": 447,
    "SouthLanarkshire-Ward_15 Blantyre": 163,
    "SouthAyrshire-Ward-7 Maybole-North-Carrick-and-Coylton": 137,
    "Highland-Dingwall_and_Seaforth": 38,
    "SouthLanarkshire-Ward_11 Rutherglen_South": 623,
    "ArgyllAndBute-ward-2-kintyre-and-the-islands": 24,
    "DumfriesAndGalloway-Ward-10 Annandale-South": 46,
    "Aberdeenshire-ward-2-troup": 76,
    "Edinburgh-Ward_6 Corstorphine_Murrayfield": 464,
    "Glasgow-Ward-22-Dennistoun": 390,
    "Highland-Tain_and_Easter_Ross": 104,
    "DumfriesAndGalloway-Ward-7 East-End": 384,
    "SouthLanarkshire-Ward_12 Rutherglen_Central_and_North": 1,
    "Edinburgh-Ward_8 Colinton_Fairmilehead": 143,
    "Clackmannanshire-Ward 5_East_2022_6697": 237,
    "Aberdeenshire-ward-16-banchory-and-mid-deeside": 176,
    "Comhairle nan Eilean Siar-Ward 08": 51,
    "Stirling-ward-5-stirling-west": 223,
    "Highland-Inverness_Ness_side": 23,
    "Aberdeen-Airyhall-Broomhill-Garthdee": 224,
    "DumfriesAndGalloway-Ward-8 Lochar": 152,
    "DumfriesAndGalloway-Ward-3 Dee-and-Glenkens": 52,
    "Minneapolis BET 09": 2098,
    "Minneapolis BET 13": 6713,
    "Minneapolis BET 17": 16863,
    "Minneapolis BET 21": 2703,
}

# datafiles = [
#     # ("Scotland/2022/preferenceprofile_v0001_ward-8-mid-formartine_06052022_172123.blt", 4),
#     ("Scotland/GCC_07_Anderson_ballots.txt", 4),
# ]


def run_audit():
    reps = 3
    counter = 0  # 1-5166

    # -3 == new without new ub
    # -1 == baseline without new ub
    # 0 == baseline (with new ub)
    # 3 == new
    # 4 == new without lse
    # 5 == new without dlb
    versions = [4, 5, 0, 3, -1, -3]

    # global seats
    print(
        "datafile, candidates, seats, quota, init_ub, found_lb, found_ub, nodes_exp, minlps_solved, solve(s), time(s), lse, dlb, eqlb, new_ub")
    for version in versions:
        for (datafile, seats) in datafiles:
            # counter += 1
            # print(counter); continue
            # if counter != int(os.environ['SLURM_ARRAY_TASK_ID']): continue
            if "example" in datafile:
                path = "./data/" + datafile
            else:
                path = "../stv-rla/data/" + datafile
            displayname = displaynames[datafile]
            # candidates = [0]
            # seats = 0
            # if path.endswith(".blt"):
            #     candidates, ballots, _, cid2num, totvotes, seats = read_ballots_blt(path)
            # print(f"{displayname}, {len(candidates)}, {seats}, {counter}"); continue
            sys.argv = ['', '-d', path, '-log', f"log_{datafile.replace('/', '')}_{version}.log", '-s', str(seats),
                        '-pc', '1', '-g', '0.01', '-agap', '0', '-limit', '10800', '-displayname', displayname, '-m']
            if version >= 0:  # new ub
                sys.argv += ['-ub', str(ubs[displayname])]
            if abs(version) == 3:  # new
                sys.argv += ['-lse', '-eqlb', '-dlb']
            if version == 4:
                sys.argv += ['-dlb', '-eqlb']
            if version == 5:
                sys.argv += ['-eqlb', '-lse']
            for _ in range(reps):
                counter += 1
                # print(version, datafile, counter); continue
                if counter != int(os.environ['SLURM_ARRAY_TASK_ID']): continue
                # print(" ".join(sys.argv))
                # with Profile() as profile:
                exec(open("pymarginstv.py").read())
                    # (
                    #     Stats(profile)
                    #     .strip_dirs()
                    #     .sort_stats(SortKey.TIME)
                    #     .print_stats()
                    # )


def run_ub():
    for (datafile, _) in datafiles:
        path = "/Users/aekk0001/Documents/stv-rla/data/" + datafile
        if path.endswith(".txt"):
            path = path.split(".txt")[0] + ".blt"
            # outfile = path.split(".blt")[0] + ".json"
            # os.system(f'/Users/aekk0001/Documents/ConcreteSTV/target/debug/blt_to_stv "{path}" --out "{outfile}"')
        # else:
        #     continue
        if path.endswith(".blt"):
            path = path.split(".blt")[0] + ".json"
        if path.endswith(".json"):
            outfile = path.split(".json")[0] + ".vchange"
            # if outfile not in allFiles:
            print(f'{path} 1st:')
            os.system(f'/Users/aekk0001/Documents/ConcreteSTV/target/debug/change_outcomes Minimal "{path}" -o "{outfile}"')
            # print(f'{path} 2nd:')
            # os.system(f'/Users/aekk0001/Documents/ConcreteSTV/target/debug/change_outcomes ACT2021 "{outfile}" -o "{outfile}"')
            # print(f'{path} 3rd:')
            # os.system(f'/Users/aekk0001/Documents/ConcreteSTV/target/debug/change_outcomes ACT2021 "{outfile}" -o "{outfile}"')
            # with open(outfile) as file:
            #     res = json.load(file)
            #     print("X")
            # # # os.system(f'/Users/aekk0001/Documents/ConcreteSTV/target/release/blt_to_stv "{path}" -o "{outfile}"')
        else:
            pass
            # print("path does not end with .blt")


def get_ub_csv():
    print("datafile, ub")
    for (datafile, _) in datafiles:
        path = "/Users/aekk0001/Documents/stv-rla/data/" + datafile
        if path.endswith(".txt"):
            path = path.split(".txt")[0] + ".json"
        if path.endswith(".blt"):
            path = path.split(".blt")[0] + ".json"
        if path.endswith(".json"):
            infile = path.split(".json")[0] + ".vchange"
            with open(infile) as file:
                res = json.load(file)
                min_ub = min([change["ballots"]["n"] for change in res["changes"]])
                print(f'{displaynames[datafile]}, {min_ub}')


def save_ub_changes_to_json():
    for (datafile, _) in datafiles:
        path = "/Users/aekk0001/Documents/stv-rla/data/" + datafile
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
        path = "/Users/aekk0001/Documents/stv-rla/data/" + datafile
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


if __name__ == "__main__":
    run_audit()
    # txt_to_blt()
    # run_ub()
    # get_ub_csv()
    # save_ub_changes_to_json()


# allFiles = glob.glob("/Users/aekk0001/Documents/stv-rla/data/Scotland/2022/*")
#
# for file in allFiles:
#     if file.endswith(".stv"):
#         candidates, ballots, _, cid2num, totvotes = read_ballots_stv(file)
#     elif file.endswith(".blt"):
#         candidates, ballots, _, cid2num, totvotes, seats = read_ballots_blt(file)
#     elif file.endswith(".json"):
#         candidates, ballots, _, cid2num, totvotes = read_ballots_json(file)
#     elif file.endswith(".txt"):
#         candidates, ballots, _, cid2num, totvotes = read_ballots_txt(file)
#     else:
#         continue
#     # print(len(candidates), len(ballots), totvotes, file.split("/")[-1])
#     if 10 >= len(candidates) >= 8:
#         # print(f'("{file}", {seats})')
#         pass
#     elif len(candidates) < 8:
#         print(f'("{file.split("/data/")[1]}", {seats}),', flush=True)

# #
# txt = """Aberdeen/PreferenceProfile_V0001_Airyhall-Broomhill-Garthdee-Ward_06052022_160546.txt
# Aberdeen/PreferenceProfile_V0001_Bridge-of-Don-Ward_06052022_160546.txt
# Aberdeen/PreferenceProfile_V0001_Dyce-Bucksburn-Danestone-Ward_06052022_160545.txt
# Aberdeen/PreferenceProfile_V0001_George-St-Harbour-Ward_06052022_160545.txt
# Aberdeen/PreferenceProfile_V0001_Hazlehead-Queens-Cross-Countesswells-Ward_06052022_160545.txt
# Aberdeen/PreferenceProfile_V0001_Hilton-Woodside-Stockethill-Ward_06052022_160546.txt
# Aberdeen/PreferenceProfile_V0001_Kincorth-Nigg-Cove-Ward_06052022_160546.txt
# Aberdeen/PreferenceProfile_V0001_Kingswells-Sheddocksley-Summerhill-Ward_06052022_160546.txt
# Aberdeen/PreferenceProfile_V0001_Lower-Deeside-Ward_06052022_160546.txt
# Aberdeen/PreferenceProfile_V0001_Midstocket-Rosemount-Ward_06052022_160545.txt
# Aberdeen/PreferenceProfile_V0001_Northfield-Mastrick-North-Ward_06052022_160545.txt
# Aberdeen/PreferenceProfile_V0001_Tillydrone-Seaton-Old-Aberdeen-Ward_06052022_160546.txt
# Aberdeen/PreferenceProfile_V0001_Torry-Ferryhill-Ward_06052022_160545.txt
# Aberdeenshire/preferenceprofile_v0001_ward-1-banff-and-district_06052022_172114.csv
# Aberdeenshire/preferenceprofile_v0001_ward-10-west-garioch_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-11-inverurie-and-district_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-12-east-garioch_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-13-westhill-and-district_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-14-huntly-strathbogie-and-howe-of-alford_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-15-aboyne-upper-deeside-and-donside_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-16-banchory-and-mid-deeside_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-17-north-kincardine_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-18-stonehaven-and-lower-deeside_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-19-mearns_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-2-troup_06052022_172123.csv
# Aberdeenshire/preferenceprofile_v0001_ward-3-fraserburgh-and-district_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-4-central-buchan_06052022_172124.csv
# Aberdeenshire/preferenceprofile_v0001_ward-5-peterhead-north-and-rattray_06052022_172118.csv
# Aberdeenshire/preferenceprofile_v0001_ward-6-peterhead-south-and-cruden_06052022_172115.csv
# Aberdeenshire/preferenceprofile_v0001_ward-7-turriff-and-district_06052022_172118.csv
# Aberdeenshire/preferenceprofile_v0001_ward-8-mid-formartine_06052022_172123.csv
# Aberdeenshire/preferenceprofile_v0001_ward-9-ellon-and-district_06052022_172124.csv
# Angus/PreferenceProfile_V0001_Ward-1---Kirriemuir-and-Dean_06052022_150515 (1).txt
# Angus/PreferenceProfile_V0001_Ward-2---Brechin-and-Edzell_06052022_150515.txt
# Angus/PreferenceProfile_V0001_Ward-3---Forfar-and-District_06052022_150515.txt
# Angus/PreferenceProfile_V0001_Ward-4---Monifieth-and-Sidlaw_06052022_150515.txt
# Angus/PreferenceProfile_V0001_Ward-5---Carnoustie-and-District_06052022_150514 (1).txt
# Angus/PreferenceProfile_V0001_Ward-6---Arbroath-West-Letham-and-Friockheim_06052022_150511.txt
# Angus/PreferenceProfile_V0001_Ward-7---Arbroath-East-and-Lunan_06052022_150515.txt
# Angus/PreferenceProfile_V0001_Ward-8---Montrose-and-District_06052022_150515.txt
# ArgyllAndBute/preferenceprofile_v0001_ward-1-south-kintyre_06052022_120128.blt
# ArgyllAndBute/preferenceprofile_v0002_ward-2-kintyre-and-the-islands_06052022_130502.blt
# ArgyllAndBute/preferenceprofile_v0003_ward-3-mid-argyll_06052022_133803.blt
# ArgyllAndBute/preferenceprofile_v0004_ward-4-oban-south-and-the-isles_06052022_143143.blt
# ArgyllAndBute/preferenceprofile_v0005_ward-5-oban-north-and-lorn_06052022_151453.blt
# ArgyllAndBute/preferenceprofile_v0007_ward-6-cowal_06052022_160055.blt
# ArgyllAndBute/preferenceprofile_v0008_ward-7-dunoon_06052022_163322.blt
# ArgyllAndBute/preferenceprofile_v0009_ward-8-isle-of-bute_06052022_165355.blt
# ArgyllAndBute/preferenceprofile_v0010_ward-9-lomond-north_06052022_173349.blt
# ArgyllAndBute/preferenceprofile_v0012_ward-10-helensburgh-central_06052022_182005.blt
# ArgyllAndBute/preferenceprofile_v0012_ward-11-helensburgh-and-lomond-south_06052022_182005.blt
# Clackmannanshire/clacks_W1_West_2022_6693.txt
# Clackmannanshire/clacks_W2_North_2022_6694.txt
# Clackmannanshire/clacks_W3_Central_2022_6695.txt
# Clackmannanshire/clacks_W4_South_2022_6696.txt
# Clackmannanshire/clacks_W5_East_2022_6697.txt
# Comhairle/cnesair_ward02_preferenceprofile.txt
# Comhairle/cnesair_ward07_preferenceprofile.txt
# Comhairle/cnesair_ward08_preferenceprofile.txt
# Comhairle/cnesair_ward09_preferenceprofile.txt
# Comhairle/cnesair_ward10_preferenceprofile.txt
# Comhairle/cnesair_ward_03_preferenceprofile.txt
# Comhairle/cnesair_ward_04_preferenceprofile.txt
# Comhairle/cnesair_ward_05_preferenceprofile.txt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-1---Stranraer-and-the-Rhins_06052022_171141.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-1---Strathmartine_06052022_161516.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-10---Annandale-South_06052022_171202.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-11---Annandale-North_06052022_171202.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-12---Annandale-East-and-Eskdale_06052022_171202.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-2---Lochee_06052022_161513.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-2---Mid-Galloway-and-Wigtown-West_06052022_171201.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-3---Dee-and-Glenkens_06052022_171147.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-3---West-End_06052022_161516.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-4---Castle-Douglas-and-Crocketford_06052022_171202.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-4---Coldside_06052022_161514.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-5---Abbey_06052022_171201.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-5---Maryfield_06052022_161515.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-6---North-East_06052022_161516.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-6---North-West-Dumfries_06052022_171201.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-7---East-End_06052022_161516.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-7---Mid-and-Upper-Nithsdale_06052022_171202.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-8---Lochar_06052022_171202.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-8---The-Ferry_06052022_161517.blt
# DumfriesAndGalloway/PreferenceProfile_V0001_Ward-9---Nith_06052022_171202.blt
# EastAyrshire/PreferenceProfile-V0002-Ward-4-Kilmarnock-East-and-Hurlford-06052022-145128.blt.pdf
# EastAyrshire/PreferenceProfile-Ward-6-Irvine-Valley.pdf
# EastAyrshire/PreferenceProfile-Ward-7-Ballochmyle.pdf
# EastAyrshire/PreferenceProfile-Ward-8-Cumnock-and-New-Cumnock.pdf
# EastAyrshire/PreferenceProfile-Ward-9-Doon-Valley.pdf
# EastAyrshire/PreferenceProfileReportWard1Annick.pdf
# EastAyrshire/PreferenceProfileReportWard2KilmarnockNorth.pdf
# EastAyrshire/PreferenceProfileReportWard3KilmarnockWestandCrosshouse.pdf
# EastAyrshire/PreferenceProfileWard-5-Kilmarnock-South.pdf
# EastDunbarton/edunbarton22_preference_profile_-_ward-5_-_bishopbriggs_south.xls
# EastDunbarton/edunbarton22_preference_profile_w1.xlsx
# EastDunbarton/edunbarton22_preference_profile_ward_2.xlsx
# EastDunbarton/edunbarton22_preference_profile_ward_3.xlsx
# EastDunbarton/edunbarton22_preference_profile_ward_4.xlsx
# EastDunbarton/edunbarton22_preference_profile_ward_6.xlsx
# EastDunbarton/edunbarton22_preference_profile_ward_7.xlsx
# EastLothian/elothian22_PreferenceProfile_V0001_Ward_1___Musselburgh_06052022_153935.blt
# EastLothian/elothian22_PreferenceProfile_V0001_Ward_2___Preston_Seton_and_Gosford_06052022_153931.blt
# EastLothian/elothian22_PreferenceProfile_V0001_Ward_3___Tranent_Wallyford_and_Macmerry_06052022_153937.blt
# EastLothian/elothian22_PreferenceProfile_V0001_Ward_4___North_Berwick_Coastal_06052022_153938.blt
# EastLothian/elothian22_PreferenceProfile_V0001_Ward_5___Haddington_and_Lammermuir_06052022_153938.blt
# EastLothian/elothian22_PreferenceProfile_V0001_Ward_6___Dunbar_and_East_Linton_06052022_153938.blt
# EastRenfrewshire/Preference_Profile_Report_W1.pdf
# EastRenfrewshire/Preference_Profile_Report_W2.pdf
# EastRenfrewshire/Preference_Profile_Report_W4.pdf
# EastRenfrewshire/Preference_Profile_Report_W5.pdf
# EastRenfrewshire/Preference_profile_report_W3.pdf
# Edinburgh/PreferenceProfile_V0001_Ward_10___Morningside_06052022_160625.blt
# Edinburgh/PreferenceProfile_V0001_Ward_11___City_Centre_06052022_155600.blt
# Edinburgh/PreferenceProfile_V0001_Ward_12___Leith_Walk_06052022_160625.blt
# Edinburgh/PreferenceProfile_V0001_Ward_13___Leith_06052022_155600.blt
# Edinburgh/PreferenceProfile_V0001_Ward_14___Craigentinny_Duddingston_06052022_160625.blt
# Edinburgh/PreferenceProfile_V0001_Ward_15___Southside_Newington_06052022_155603.blt
# Edinburgh/PreferenceProfile_V0001_Ward_16___Liberton_Gilmerton_06052022_160625.blt
# Edinburgh/PreferenceProfile_V0001_Ward_17___Portobello_Craigmillar_06052022_155600.blt
# Edinburgh/PreferenceProfile_V0001_Ward_1___Almond_06052022_155516.blt
# Edinburgh/PreferenceProfile_V0001_Ward_2___Pentland_Hills_06052022_160611.blt
# Edinburgh/PreferenceProfile_V0001_Ward_3___Drum_Brae_Gyle_06052022_155559.blt
# Edinburgh/PreferenceProfile_V0001_Ward_4___Forth_06052022_160611.blt
# Edinburgh/PreferenceProfile_V0001_Ward_5___Inverleith_06052022_155559.blt
# Edinburgh/PreferenceProfile_V0001_Ward_6___Corstorphine_Murrayfield_06052022_160625.blt
# Edinburgh/PreferenceProfile_V0001_Ward_7___Sighthill_Gorgie_06052022_155557.blt
# Edinburgh/PreferenceProfile_V0001_Ward_8___Colinton_Fairmilehead_06052022_160625.blt
# Edinburgh/PreferenceProfile_V0001_Ward_9___Fountainbridge_Craiglockhart_06052022_155600.blt
# Falkirk/falkirk22_Preference Profile_W1.csv
# Falkirk/falkirk22_Preference Profile_W2.csv
# Falkirk/falkirk22_Preference Profile_W3.csv
# Falkirk/falkirk22_Preference Profile_W4.csv
# Falkirk/falkirk22_Preference Profile_W5.csv
# Falkirk/falkirk22_Preference Profile_w6.csv
# Falkirk/falkirk22_Preference Profile_w7.csv
# Falkirk/falkirk22_Preference Profile_w8.csv
# Falkirk/falkirk22_Preference Profile_w9.csv
# Fife/PreferenceProfile_V0001_Ward-1-West-Fife-and-Coastal-Villages_06052022_145537.blt
# Fife/PreferenceProfile_V0001_Ward-10-Kirkcaldy-North_06052022_151928.blt
# Fife/PreferenceProfile_V0001_Ward-11-Kirkcaldy-Central_06052022_145551.blt
# Fife/PreferenceProfile_V0001_Ward-12-Kirkcaldy-East_06052022_151925.blt
# Fife/PreferenceProfile_V0001_Ward-13-Glenrothes-West-and-Kinglassie_06052022_145551.blt
# Fife/PreferenceProfile_V0001_Ward-14-Glenrothes-North-Leslie-and-Markinch_06052022_151925.blt
# Fife/PreferenceProfile_V0001_Ward-15-Glenrothes-Central-and-Thornton_06052022_145551.blt
# Fife/PreferenceProfile_V0001_Ward-16-Howe-Of-Fife-and-Tay-Coast_06052022_151928.blt
# Fife/PreferenceProfile_V0001_Ward-17-Tay-Bridgehead_06052022_145551.blt
# Fife/PreferenceProfile_V0001_Ward-18-St.-Andrews_06052022_151928.blt
# Fife/PreferenceProfile_V0001_Ward-19-East-Neuk-and-Landward_06052022_145551.blt
# Fife/PreferenceProfile_V0001_Ward-2-Dunfermline-North_06052022_151927.blt
# Fife/PreferenceProfile_V0001_Ward-20-Cupar_06052022_151928.blt
# Fife/PreferenceProfile_V0001_Ward-21-Leven-Kennoway-and-Largo_06052022_145552.blt
# Fife/PreferenceProfile_V0001_Ward-22-Buckhaven-Methil-and-Wemyss-Villages_06052022_151928.blt
# Fife/PreferenceProfile_V0001_Ward-3-Dunfermline-Central_06052022_145551.blt
# Fife/PreferenceProfile_V0001_Ward-4-Dunfermline-South_06052022_151924.blt
# Fife/PreferenceProfile_V0001_Ward-5-Rosyth_06052022_145544.blt
# Fife/PreferenceProfile_V0001_Ward-6-Inverkeithing-and-Dalgety-Bay_06052022_151927.blt
# Fife/PreferenceProfile_V0001_Ward-7-Cowdenbeath_06052022_145532.blt
# Fife/PreferenceProfile_V0001_Ward-8-Lochgelly-Cardenden-and-Benarty_06052022_151928.blt
# Fife/PreferenceProfile_V0001_Ward-9-Burntisland-Kinghorn-and-Western-Kirkcaldy_06052022_145551.blt
# Glasgow/PreferenceProfile_V0001_Ward-1-Linn_06052022_163754.blt
# Glasgow/PreferenceProfile_V0001_Ward-10-Anderston-City-Yorkhill_06052022_170256.blt
# Glasgow/PreferenceProfile_V0001_Ward-11-Hillhead_06052022_163755.blt
# Glasgow/PreferenceProfile_V0001_Ward-12-Victoria-Park_06052022_163755.blt
# Glasgow/PreferenceProfile_V0001_Ward-13-Garscadden-Scotstounhill_06052022_165250.blt
# Glasgow/PreferenceProfile_V0001_Ward-14-Drumchapel-Anniesland_06052022_170258.blt
# Glasgow/PreferenceProfile_V0001_Ward-15-Maryhill_06052022_165258.blt
# Glasgow/PreferenceProfile_V0001_Ward-16-Canal_06052022_163755.blt
# Glasgow/PreferenceProfile_V0001_Ward-17-Springburn-Robroyston_06052022_170301.blt
# Glasgow/PreferenceProfile_V0001_Ward-18-East-Centre_06052022_165259.blt
# Glasgow/PreferenceProfile_V0001_Ward-19-Shettleston_06052022_170301.blt
# Glasgow/PreferenceProfile_V0001_Ward-2-Newlands-Auldburn_06052022_165250.blt
# Glasgow/PreferenceProfile_V0001_Ward-20-Baillieston_06052022_170301.blt
# Glasgow/PreferenceProfile_V0001_Ward-21-North-East_06052022_170301.blt
# Glasgow/PreferenceProfile_V0001_Ward-22-Dennistoun_06052022_163757.blt
# Glasgow/PreferenceProfile_V0001_Ward-23-Partick-East-Kelvindale_06052022_170257.blt
# Glasgow/PreferenceProfile_V0001_Ward-3-Greater-Pollok_06052022_163750.blt
# Glasgow/PreferenceProfile_V0001_Ward-4-Cardonald_06052022_163754.blt
# Glasgow/PreferenceProfile_V0001_Ward-5-Govan_06052022_165258.blt
# Glasgow/PreferenceProfile_V0001_Ward-6-Pollokshields_06052022_170301.blt
# Glasgow/PreferenceProfile_V0001_Ward-7-Langside_06052022_165250.blt
# Glasgow/PreferenceProfile_V0001_Ward-8-Southside-Central_06052022_165258.blt
# Glasgow/PreferenceProfile_V0001_Ward-9-Calton_06052022_163749.blt
# Highland/PreferenceProfile_V0001_Aird_and_Loch_Ness_06052022_161539.blt
# Highland/PreferenceProfile_V0001_Badenoch_and_Strathspey_06052022_161540.blt
# Highland/PreferenceProfile_V0001_Black_Isle_06052022_161539.blt
# Highland/PreferenceProfile_V0001_Cromarty_Firth_06052022_161538.blt
# Highland/PreferenceProfile_V0001_Culloden_and_Ardersier_06052022_161539.blt
# Highland/PreferenceProfile_V0001_Dingwall_and_Seaforth_06052022_161539.blt
# Highland/PreferenceProfile_V0001_East_Sutherland_and_Edderton_06052022_161530.blt
# Highland/PreferenceProfile_V0001_Eilean_a__Che___06052022_161539.blt
# Highland/PreferenceProfile_V0001_Fort_William_and_Ardnamurchan_06052022_161540.blt
# Highland/PreferenceProfile_V0001_Inverness_Central_06052022_161539.blt
# Highland/PreferenceProfile_V0001_Inverness_Millburn_06052022_161539.blt
# Highland/PreferenceProfile_V0001_Inverness_Ness_side_06052022_161539.blt
# Highland/PreferenceProfile_V0001_Inverness_South_06052022_161540.blt
# Highland/PreferenceProfile_V0001_Inverness_West_06052022_161539.blt
# Highland/PreferenceProfile_V0001_Nairn_and_Cawdor_06052022_161539.blt
# Highland/PreferenceProfile_V0001_North_West_and_Central_Sutherland_06052022_161534.blt
# Highland/PreferenceProfile_V0001_Tain_and_Easter_Ross_06052022_161537.blt
# Highland/PreferenceProfile_V0001_Thurso_and_Northwest_Caithness_06052022_161528.blt
# Highland/PreferenceProfile_V0001_Wester_Ross_Strathpeffer_and_Lochalsh_06052022_161539.blt
# Highland/PreferenceProfile_V0001_Wick_and_East_Caithness_06052022_161532.blt
# Inverclyde/PreferenceProfile_Ward-2.blt
# Inverclyde/PreferenceProfile_Ward-3.blt
# Inverclyde/PreferenceProfile_Ward-4.blt
# Inverclyde/PreferenceProfile_Ward-5.blt
# Inverclyde/PreferenceProfile_Ward-6.blt
# Inverclyde/PreferenceProfile_Ward-7.blt
# Midlothian/PreferenceProfile_V0001_Ward_2___Bonnyrigg_06052022_151836.blt
# Midlothian/Ward_1_Penicuik_preference_profile__open_from_within_MS_Word_or_similar_.blt
# Midlothian/Ward_3_Dalkeith_preference_profile__open_from_within_MS_Word_or_similar_.blt
# Midlothian/Ward_4_Midlothian_West_preference_profile__open_from_within_MS_Word_or_similar_.blt
# Midlothian/Ward_5_Midlothian_East_preference_profile__open_from_within_MS_Word_or_similar_.blt
# Midlothian/Ward_6_Midlothian_South_Dalkeith_preference_profile__open_from_within_MS_Word_or_similar_.blt
# Moray/moray22_ward1.blt
# Moray/moray22_ward2.blt
# Moray/moray22_ward4.blt
# Moray/moray22_ward5.blt
# Moray/moray22_ward6.blt
# Moray/moray22_ward7.blt
# Moray/moray22_ward8.blt
# NorthAyrshire/Preference Profile Ardrossan.pdf
# NorthAyrshire/Preference Profile Arran.pdf
# NorthAyrshire/Preference Profile Garnock Valley.pdf
# NorthAyrshire/Preference Profile Irvine East.pdf
# NorthAyrshire/Preference Profile Irvine South.pdf
# NorthAyrshire/Preference Profile Irvine West.pdf
# NorthAyrshire/Preference Profile Kilwinning.pdf
# NorthAyrshire/Preference Profile North Coast.pdf
# NorthAyrshire/Preference Profile Saltcoats and Stevenston.pdf
# NorthLanarkshire/Preference Profile WArd 14 Thorniewood.xlsx
# NorthLanarkshire/Preference Profile WArd 15 Bellshill.xlsx
# NorthLanarkshire/Preference Profile WArd 4 Cumbernauld East.xlsx
# NorthLanarkshire/Preference Profile WArd 7 Coatbridge North.xlsx
# NorthLanarkshire/Preference Profile WArd 9 Airdrie Central.xlsx
# NorthLanarkshire/Preference Profile Ward 1 Kilsyth.xlsx
# NorthLanarkshire/Preference Profile Ward 10 Coatbridge West.xlsx
# NorthLanarkshire/Preference Profile Ward 11 Coatbridge South.xlsx
# NorthLanarkshire/Preference Profile Ward 12 Airdrie South.xlsx
# NorthLanarkshire/Preference Profile Ward 13 Fortissat.xlsx
# NorthLanarkshire/Preference Profile Ward 16 Mossend and Holytown.xlsx
# NorthLanarkshire/Preference Profile Ward 17 Motherwell West.xlsx
# NorthLanarkshire/Preference Profile Ward 18 Motherwell North.xlsx
# NorthLanarkshire/Preference Profile Ward 19 Motherwell South East and Ravenscraig.xlsx
# NorthLanarkshire/Preference Profile Ward 2 Cumbernauld North.xlsx
# NorthLanarkshire/Preference Profile Ward 20 Murdostoun.xlsx
# NorthLanarkshire/Preference Profile Ward 21 Wishaw.xlsx
# NorthLanarkshire/Preference Profile Ward 3 Cumbernauld South.xlsx
# NorthLanarkshire/Preference Profile Ward 5 Stepps, Chryston and Muirhead.xlsx
# NorthLanarkshire/Preference Profile Ward 6 Gartcosh, Glenboig and Moodiesburn.xlsx
# NorthLanarkshire/Preference Profile Ward 8 Airdrie North.xlsx
# OrkneyIslands/orkney22-W2.blt
# OrkneyIslands/orkney22-W3.blt
# OrkneyIslands/orkney22-W4.blt
# OrkneyIslands/orkney22-W5.blt
# OrkneyIslands/orkney22-W6.blt
# OrkneyIslands/orkney22_W1.blt
# PerthAndKinross/Ward_10_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_11_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_12_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_1_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_2_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_3_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_4_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_5_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_6_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_7_-_Preference_Profile_Report_1.pdf
# PerthAndKinross/Ward_8_-_Preference_Profile_Report.pdf
# PerthAndKinross/Ward_9_-_Preference_Profile_Report.pdf
# Renfrewshire/Preference_profile_for_Ward_10_Houston_Crosslee_and_Linwood.pdf
# Renfrewshire/Preference_profile_for_Ward_11_Bishopton_Bridge_of_Weir_and_Langbank.pdf
# Renfrewshire/Preference_profile_for_Ward_12_Erskine_and_Inchinnan.pdf
# Renfrewshire/Preference_profile_for_Ward_1_Renfrew_North_and_Braehead.pdf
# Renfrewshire/Preference_profile_for_Ward_2_Renfrew_South_and_Gallowhill.pdf
# Renfrewshire/Preference_profile_for_Ward_3_Paisley_Northeast_and_Ralston.pdf
# Renfrewshire/Preference_profile_for_Ward_4_Paisley_Northwest.pdf
# Renfrewshire/Preference_profile_for_Ward_5_Paisley_East_and_Central.pdf
# Renfrewshire/Preference_profile_for_Ward_6_Paisley_Southeast.pdf
# Renfrewshire/Preference_profile_for_Ward_7_Paisley_Southwest.pdf
# Renfrewshire/Preference_profile_for_Ward_8_Johnstone_South_and_Elderslie.pdf
# Renfrewshire/Preference_profile_for_Ward_9_Johnstone_North_Kilbarchan_Howwood_and_Lochwinnoch.pdf
# ShetlandIslands/PreferenceProfile_V0001_North_Isles_Ward_05082022_112827.blt
# ShetlandIslands/PreferenceProfile_V0001_Ward_3___Shetland_West_06052022_120841.blt
# ShetlandIslands/PreferenceProfile_V0001_Ward_4___Shetland_Central_06052022_120841.blt
# ShetlandIslands/PreferenceProfile_V0001_Ward_5___Lerwick_North_and_Bressay_06052022_120841.blt
# ShetlandIslands/PreferenceProfile_V0001_Ward_6___Lerwick_South_06052022_120841.blt
# ShetlandIslands/PreferenceProfile_V0001_Ward_7___Shetland_South_06052022_120840.blt
# SouthAyrshire/PreferenceProfile_V0001_Ward-1---Troon_06052022_142627.csv
# SouthAyrshire/PreferenceProfile_V0001_Ward-2---Prestwick_06052022_142624.csv
# SouthAyrshire/PreferenceProfile_V0001_Ward-4---Ayr-East_06052022_142626.csv
# SouthAyrshire/PreferenceProfile_V0001_Ward-5---Ayr-West_06052022_142628.csv
# SouthAyrshire/PreferenceProfile_V0001_Ward-6---Kyle_06052022_142627.csv
# SouthAyrshire/PreferenceProfile_V0001_Ward-7---Maybole-North-Carrick-and-Coylton_06052022_142628.csv
# SouthAyrshire/PreferenceProfile_V0001_Ward-8---Girvan-and-South-Carrick_06052022_142628.csv
# SouthAyrshire/PreferenceProfile_V0009_Ward-3---Ayr-North_10052022_111313.csv
# SouthLanarkshire/PreferenceProfile_V0001_Ward_10___East_Kilbride_East.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_11___Rutherglen_South.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_12___Rutherglen_Central_and_North.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_13___Cambuslang_West.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_14___Cambuslang_East.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_15___Blantyre.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_16___Bothwell_and_Uddingston.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_17___Hamilton_North_and_East.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_18___Hamilton_West_and_Earnock.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_19___Hamilton_South.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_1___Clydesdale_West.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_20___Larkhall.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_2___Clydesdale_North.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_3___Clydesdale_East.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_4___Clydesdale_South.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_5___Avondale_and_Stonehouse.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_6___East_Kilbride_South.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_7___East_Kilbride_Central_South.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_8___East_Kilbride_Central_North.txt
# SouthLanarkshire/PreferenceProfile_V0001_Ward_9___East_Kilbride_West.txt
# Stirling/preferenceprofile_v0001_ward-1-trossachs-and-teith_06052022_124254.blt
# Stirling/preferenceprofile_v0001_ward-2-forth-and-endrick_06052022_124253.blt
# Stirling/preferenceprofile_v0001_ward-3-dunblane-and-bridge-of-allan_06052022_124253.blt
# Stirling/preferenceprofile_v0001_ward-4-stirling-north_06052022_124253.blt
# Stirling/preferenceprofile_v0001_ward-5-stirling-west_06052022_124253.blt
# Stirling/preferenceprofile_v0001_ward-6-stirling-east_06052022_124253.blt
# Stirling/preferenceprofile_v0001_ward-7-bannockburn_06052022_124254.blt
# WestDunbartonshire/preferenceprofile_v0001_ward-1-lomond_06052022_120102.csv
# WestDunbartonshire/preferenceprofile_v0001_ward-2-leven_06052022_120059.csv
# WestDunbartonshire/preferenceprofile_v0001_ward-3-dumbarton_06052022_120059.csv
# WestDunbartonshire/preferenceprofile_v0001_ward-4-kilpatrick_06052022_120059.csv
# WestDunbartonshire/preferenceprofile_v0001_ward-5-clydebank-central_06052022_120100.csv
# WestDunbartonshire/preferenceprofile_v0001_ward-6-clydebank-waterfront_06052022_120103.csv
# WestLothian/PreferenceProfile_V0001_Ward-1---Linlithgow_06052022_160231.pdf
# WestLothian/PreferenceProfile_V0001_Ward-2---Broxburn-Uphall-and-Winchburgh_06052022_160218.pdf
# WestLothian/PreferenceProfile_V0001_Ward-3---Livingston-North_06052022_160234.pdf
# WestLothian/PreferenceProfile_V0001_Ward-4---Livingston-South_06052022_160228.pdf
# WestLothian/PreferenceProfile_V0001_Ward-5---East-Livingston-and-East-Calder_06052022_160233.pdf
# WestLothian/PreferenceProfile_V0001_Ward-6---Fauldhouse-and-the-Breich-Valley_06052022_160234.pdf
# WestLothian/PreferenceProfile_V0001_Ward-7---Whitburn-and-Blackburn_06052022_160234.pdf
# WestLothian/PreferenceProfile_V0001_Ward-8---Bathgate_06052022_160235.pdf
# WestLothian/PreferenceProfile_V0001_Ward-9---Armadale-and-Blackridge_06052022_160235.pdf"""
# #
#
# for line in txt.split("\n"):
#     council, ward = line.split("/")
#     if council in ["EastAyrshire", "EastDunbarton", "EastRenfrewshire", "NorthAyrshire", "NorthLanarkshire",
#                    "PerthAndKinross", "Renfrewshire", "WestLothian"]:
#         continue
#     filename = ward
#     filename = filename.split('.')[0] + ".blt"
#     if "PreferenceProfile_V0001_" in ward:
#         ward = ward.split("_V0001_")[1]
#     if "preferenceprofile_v0001_" in ward:
#         ward = ward.split("_v0001_")[1]
#     if "PreferenceProfile_V0009_" in ward:
#         ward = ward.split("_V0009_")[1]
#     if "." in ward:
#         ward = ward.split(".")[0]
#     if "_06052022_" in ward:
#         ward = ward.split("_06052022_")[0]
#     if "_10052022_" in ward:
#         ward = ward.split("_10052022_")[0]
#     if "_05082022_" in ward:
#         ward = ward.split("_05082022_")[0]
#     if "_preference_profile__open_" in ward:
#         ward = ward.split("_preference_profile__open_")[0]
#     if "_preferenceprofile" in ward:
#         ward = ward.split("_preferenceprofile")[0]
#     if "preferenceprofile_" in ward:
#         ward = ward.split("preferenceprofile_")[1]
#     if "PreferenceProfile_" in ward:
#         ward = ward.split("PreferenceProfile_")[1]
#     if "---" in ward:
#         pre, post = ward.split("---")
#         ward = pre + " " + post
#     if "___" in ward:
#         pre, post = ward.split("___")
#         ward = pre + " " + post
#     # if "ard_" in ward:
#     #     pre, post = ward.split("ard_")
#     #     ward = "Ward " + post
#     # if "ard-" in ward:
#     #     pre, post = ward.split("ard-")
#     #     ward = "Ward " + post
#     print(f'"Scotland/2022/{filename}": "{council}, {ward}",')
# #
