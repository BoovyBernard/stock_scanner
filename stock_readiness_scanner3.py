"""
advanced_readiness_scanner_mtf_btd.py

Features:
 - Readiness scoring (price, volume/options flow, fundamentals)
 - Institutional flow proxy injected into final score
 - Sector detection & bulk lists (S&P500, NAS100, DOW30 fetchers)
 - Multi-sheet Excel output
 - Buy Signal logic (STRONG BUY/BUY/WATCHLIST/NO TRADE)
 - Score history persistence (readiness_history.csv) and trend detection
 - Multi-timeframe confirmation (1D, 4H, 1H)
 - Buy-The-Dip (BTD) detection (daily uptrend + small pullback)
"""

import os
import math
import time
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

# -----------------------------
# CONFIG
# -----------------------------
HIST_DAYS = 180             # daily history
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
OBV_LOOKBACK = 14
VOLUME_SPIKE_MULT = 1.5
OUTPUT_FILE = "readiness_scores.xlsx"
HISTORY_CSV = "readiness_history.csv"

# Institutional flow weighting (0..1)
INST_FLOW_WEIGHT = 0.10

# Multi-timeframe config
MTF_TIMEFRAMES = ["1d", "4h", "1h"]   # daily, 4-hour, 1-hour
MTF_CONFIRM_THRESHOLD = 2             # require this many timeframes positive (of 3) for confirmation
MTF_POSITIVE_PRICE_SCORE = 60.0       # per-timeframe price momentum score threshold considered "positive"

# Buy-the-Dip config
BTD_LOOKBACK_DAYS = 20    # consider highs over last N days
BTD_MIN_PULLBACK = 0.02   # 2% pullback (minimum)
BTD_MAX_PULLBACK = 0.08   # 8% pullback (maximum)
BTD_REQUIRE_DAILY_UPTREND = True

# Baseline tickers - adjust as needed
TOP_LEVEL_TICKERS = [
  #"A", "AA", "AAA", "AACT", "AADI", "AAIN", "AAL", "AAM", "AAME", "AAMI", "AAOI", "AAON", "AAP", "AAPG", "AAPL", "AARD", "AAT", "AAUC", "AB", "ABAT", "ABBV", "ABCB", "ABCL", "ABEO", "ABEV", "ABG", "ABL", "ABLLL", "ABLV", "ABLVW", "ABM", "ABNB", "ABOS", "ABP", "ABPWW", "ABR", "ABR^D", "ABR^E", "ABR^F", "ABSI", "ABT", "ABTC", "ABTS", "ABUS", "ABVC", "ABVE", "ABVEW", "ABVX", "ACA", "ACAD", "ACB", "ACCL", "ACCO", "ACCS", "ACDC", "ACEL", "ACET", "ACFN", "ACGL", "ACGLN", "ACGLO", "ACHC", "ACHR", "ACHV", "ACI", "ACIC", "ACIU", "ACIW", "ACLS", "ACLX", "ACM", "ACMR", "ACN", "ACNB", "ACNT", "ACOG", "ACON", "ACONW", "ACP", "ACP^A", "ACR", "ACR^C", "ACR^D", "ACRE", "ACRS", "ACRV", "ACT", "ACTG", "ACTU", "ACU", "ACV", "ACVA", "ACXP", "AD", "ADAG", "ADAM", "ADAMG", "ADAMH", "ADAMI", "ADAML", "ADAMM", "ADAMN", "ADAMZ", "ADBE", "ADC", "ADC^A", "ADCT", "ADEA", "ADGM", "ADI", "ADIL", "ADM", "ADMA", "ADNT", "ADP", "ADPT", "ADSE", 
   #        "ADSEW", "ADSK", "ADT", "ADTN", "ADTX", "ADUR", "ADUS", "ADV", "ADVB", "ADVM", "ADX", "ADXN", "AEBI", "AEC", "AEE", "AEF", "AEFC", "AEG", "AEHL", "AEHR", "AEI", "AEIS", "AEM", "AEMD", "AENT", "AENTW", "AEO", "AEON", "AEP", "AER", "AERO", "AERT", "AERTW", "AES", "AESI", "AEVA", "AEVAW", "AEXA", "AEYE", "AFB", "AFBI", "AFCG", "AFG", "AFGB", "AFGC", "AFGD", "AFGE", "AFJK", "AFJKR", "AFJKU", "AFL", "AFRI", "AFRIW", "AFRM", "AFYA", "AG", "AGAE", "AGCC", "AGCO", "AGD", "AGEN", "AGH", "AGI", "AGIO", "AGL", "AGM", "AGM^D", "AGM^E", "AGM^F", "AGM^G", "AGM^H", "AGMH", "AGNC", "AGNCL", "AGNCM", "AGNCN", "AGNCO", "AGNCP", "AGNCZ", "AGO", "AGRO", "AGRZ", "AGX", "AGYS", "AHCO", "AHG", "AHH", "AHH^A", "AHL", "AHL^D", "AHL^E", "AHL^F", "AHMA", "AHR", "AHT", "AHT^D", "AHT^F", "AHT^G", "AHT^H", "AHT^I", "AI", "AIFF", "AIFU", "AIG", "AIHS", "AII", "AIIO", "AIIOW", "AIM", "AIMD", "AIMDW", "AIN", "AIO", "AIOT", "AIP", "AIR", "AIRE", 
    #       "AIRG", "AIRI", "AIRJ", "AIRJW", "AIRO", "AIRS", "AIRT", "AIRTP", "AISP", "AISPW", "AIT", "AIV", "AIXI", "AIZ", "AIZN", "AJG", "AKA", "AKAM", "AKAN", "AKBA", "AKO/A", "AKO/B", "AKR", "AKRO", "AKTX", "AL", "ALAB", "ALAR", "ALB", "ALB^A", "ALBT", "ALC", "ALCO", "ALCY", "ALDF", "ALDFW", "ALDX", "ALE", "ALEC", "ALEX", "ALF", "ALFUW", "ALG", "ALGM", "ALGN", "ALGS", "ALGT", "ALH", "ALHC", "ALISU", "ALIT", "ALK", "ALKS", "ALKT", "ALL", "ALL^B", "ALL^H", "ALL^I", "ALL^J", "ALLE", "ALLO", "ALLR", "ALLT", "ALLY", "ALM", "ALMS", "ALMU", "ALNT", "ALNY", "ALOT", "ALPS", "ALRM", "ALRS", "ALSN", "ALT", "ALTG", "ALTG^A", "ALTI", "ALTO", "ALTS", "ALUR", "ALV", "ALVO", "ALVOW", "ALX", "ALXO", "ALZN", "AM", "AMAL", "AMAT", "AMBA", "AMBC", "AMBO", "AMBP", "AMBQ", "AMBR", "AMC", "AMCR", "AMCX", "AMD", "AME", "AMG", "AMGN", "AMH", "AMH^G", "AMH^H", "AMIX", "AMKR", "AMLX", "AMN", "AMOD", "AMODW", "AMP", "AMPG", "AMPGW", "AMPH", "AMPL", "AMPX", "AMPY", "AMR", "AMRC", "AMRK", "AMRN", "AMRX", "AMRZ", "AMS", "AMSC", "AMSF", "AMST", "AMT", "AMTB", "AMTD", "AMTM", "AMTX", "AMWD", "AMWL", "AMX", "AMZE", "AMZN", "AN", "ANAB", "ANDE", "ANEB", "ANET", "ANF", "ANG^D", "ANGH", "ANGHW", "ANGI", "ANGO", "ANGX", "ANIK", "ANIP", "ANIX", "ANL", "ANNA", "ANNAW", "ANNX", "ANPA", "ANRO", "ANSC", "ANSCW", "ANTA", "ANTX", "ANVS", "ANY", "AOD", "AOMD", "AOMN", "AOMR", "AON", "AORT", "AOS", "AOSL", "AOUT", "AP", "APA", "APACU", "APAD", "APADR", "APADU", "APAM", "APD", "APEI", "APG", "APGE", "APH", "API", "APLD", "APLE", "APLM", "APLMW", "APLS", "APLT", "APM", "APO", "APO^A", "APOG", "APOS", "APP", "APPF", "APPN", "APPS", "APRE", "APT", "APTV", "APUS", "APVO", "APWC", "APXTU", "APYX", "AQB", "AQMS", "AQN", "AQNB", "AQST", "AR", "ARAI", "ARAY", "ARBB", "ARBE", "ARBEW", "ARBK", "ARBKL", "ARCB", "ARCC", "ARCO", "ARCT", "ARDC", "ARDT", "ARDX", "ARE", 
     #      "AREB", "AREBW", "AREC", "AREN", "ARES", "ARES^B", "ARGX", "ARHS", "ARI", "ARKO", "ARKOW", "ARKR", "ARL", "ARLO", "ARLP", "ARM", "ARMK", "ARMN", "ARMP", "AROC", "AROW", "ARQ", "ARQQ", "ARQQW", "ARQT", "ARR", "ARR^C", "ARRY", "ARTL", "ARTNA", "ARTV", "ARTW", "ARVN", "ARW", "ARWR", "ARX", "AS", "ASA", "ASAN", "ASB", "ASB^E", "ASB^F", "ASBA", "ASBP", "ASBPW", "ASC", "ASG", "ASGI", "ASGN", "ASH", "ASIC", "ASIX", "ASLE", "ASM", "ASMB", "ASML", "ASND", "ASNS", "ASO", "ASPC", "ASPCR", "ASPCU", "ASPI", "ASPN", "ASPS", "ASPSW", "ASPSZ", "ASR", "ASRT", "ASRV", "ASST", "ASTC", "ASTE", "ASTH", "ASTI", "ASTL", "ASTLW", "ASTS", "ASUR", "ASX", "ASYS", "ATAI", "ATAT", "ATCH", "ATEC", "ATEN", "ATER", "ATEX", "ATGE", "ATGL", "ATH^A", "ATH^B", "ATH^D", "ATH^E", "ATHA", "ATHE", "ATHM", "ATHR", "ATHS", "ATI", "ATII", "ATIIW", "ATKR", "ATLC", "ATLCL", "ATLCP", "ATLCZ", "ATLN", "ATLO", "ATLX", "ATMC", "ATMCR", "ATMCU", "ATMCW", "ATMU", "ATMV", "ATMVR", "ATMVU", "ATNI", "ATNM", "ATO", "ATOM", "ATON", "ATOS", "ATPC", "ATR", "ATRA", "ATRC", "ATRO", "ATS", "ATUS", "ATXG", "ATXS", "ATYR", "AU", "AUB", "AUB^A", "AUBN", "AUDC", "AUGO", "AUID", "AUNA", "AUPH", "AUR", "AURA", "AURE", "AUROW", "AUST", "AUTL", "AUUD", "AUUDW", "AVA", "AVAH", "AVAL", "AVAV", "AVB", "AVBC", "AVBH", "AVBP", "AVD", "AVDL", "AVGO", "AVIR", "AVK", "AVNS", "AVNT", "AVNW", "AVO", "AVPT", "AVR", "AVT", "AVTR", "AVTX", "AVX", "AVXL", "AVY", "AWF", "AWI", "AWK", "AWP", "AWR", "AWRE", "AWX", "AX", "AXG", "AXGN", "AXIA", "AXIA^", "AXIL", "AXIN", "AXINR", "AXL", "AXON", "AXP", "AXR", "AXS", "AXS^E", "AXSM", "AXTA", "AXTI", "AYI", "AYTU", "AZ", "AZI", "AZN", "AZO", "AZTA", "AZTR", "AZZ", "B", "BA", "BA^A", "BABA", "BAC", "BAC^B", "BAC^E", "BAC^K", "BAC^L", "BAC^M", "BAC^N", "BAC^O", "BAC^P", "BAC^Q", "BAC^S", "BACC", "BACCR", "BACCU", "BACQ", "BACQR", "BAER", "BAERW", "BAFN", "BAH", "BAK", "BALL", "BALY", "BAM", "BANC", "BANC^F", "BAND", "BANF", "BANFP", "BANL", "BANR", "BANX", "BAOS", "BAP", "BARK", "BATL", "BATRA", "BATRK", "BAX", "BB", "BBAI", "BBAR", "BBBY", "BBCP", "BBD", "BBDC", "BBDO", "BBGI", "BBIO", "BBLG", "BBLGW", "BBN", "BBNX", "BBOT", "BBSI", "BBT", "BBU", "BBUC", "BBVA", "BBW", "BBWI", "BBY", "BC", "BC^A", "BC^C", "BCAB", "BCAL", "BCAR", "BCAT", "BCAX", "BCBP", "BCC", "BCDA", "BCE", "BCG", "BCH", "BCIC", "BCML", "BCO", "BCPC", "BCRX", "BCS", "BCSF", "BCTX", "BCTXW", "BCTXZ", "BCV", "BCV^A", "BCX", "BCYC", "BDC", "BDCI", "BDCIU", "BDCIW", "BDJ", "BDL", "BDMD", "BDMDW", "BDN", "BDRX", "BDSX", "BDTX", "BDX", "BE", "BEAG", "BEAGR", "BEAGU", "BEAM", "BEAT", "BEDU", "BEEM", "BEEP", "BEKE", "BELFA", "BELFB", "BEN", "BENF", "BENFW", "BEP", "BEP^A", "BEPC", "BEPH", "BEPI", "BEPJ", "BETA", "BETR", "BETRW", "BF/A", "BF/B", "BFAM", "BFC", "BFH", "BFIN", "BFK", "BFLY", "BFRG", "BFRGW", "BFRI", "BFS", "BFS^D", "BFS^E", "BFST", "BFZ", "BG", "BGB", "BGC", "BGH", "BGI", "BGIN", 
      #     "BGL", "BGLC", "BGLWW", "BGM", "BGMS", "BGMSP", "BGR", "BGS", "BGSF", "BGSI", "BGT", "BGX", "BGY", "BH", "BHAT", "BHB", "BHC", "BHE", "BHF", "BHFAL", "BHFAM", "BHFAN", "BHFAO", "BHFAP", "BHK", "BHM", "BHP", "BHR", "BHR^B", "BHR^D", "BHRB", "BHST", "BHV", "BHVN", "BIAF", "BIAFW", "BIDU", "BIIB", "BILI", "BILL", "BIO", "BIO/B", "BIOA", "BIOX", "BIP", "BIP^A", "BIP^B", "BIPC", "BIPH", "BIPI", "BIPJ", "BIRD", "BIRK", "BIT", "BITF", "BIVI", "BIYA", "BJ", "BJDX", "BJRI", "BK", "BK^K", "BKD", "BKE", "BKH", "BKHA", "BKHAR", "BKKT", "BKN", "BKNG", "BKR", "BKSY", "BKT", "BKTI", "BKU", "BKV", "BKYI", "BL", "BLBD", "BLBX", "BLCO", "BLD", "BLDP", "BLDR", "BLE", "BLFS", "BLFY", "BLIN", "BLIV", "BLK", "BLKB", "BLLN", "BLMN", "BLMZ", "BLND", "BLNE", "BLNK", "BLRX", "BLSH", "BLTE", "BLUW", "BLUWU", "BLUWW", "BLW", "BLX", "BLZE", "BLZR", "BLZRU", "BLZRW", "BMA", "BMBL", "BME", "BMEA", "BMEZ", "BMGL", "BMHL", "BMI", "BML^G", "BML^H", "BML^J", "BML^L", "BMN", "BMNR", "BMO", "BMR", "BMRA", "BMRC", "BMRN", "BMY", "BN", "BNAI", "BNAIW", "BNBX", "BNC", "BNCWW", "BNED", "BNGO", "BNH", "BNJ", "BNKK", "BNL", "BNR", "BNRG", "BNS", "BNT", "BNTC", "BNTX", "BNY", "BNZI", "BNZIW", "BOC", "BODI", "BOE", "BOF", "BOH", "BOH^A", "BOH^B", "BOKF", "BOLD", "BOLT", "BON", "BOOM", "BOOT", "BORR", "BOSC", "BOTJ", "BOW", "BOX", "BOXL", "BP", "BPACU", "BPOP", "BPOPM", "BPRN", "BPYPM", "BPYPN", "BPYPO", "BPYPP", "BQ", "BR", "BRAG", "BRBI", "BRBR", "BRBS", "BRC", "BRCB", "BRCC", "BRFH", "BRIA", "BRID", "BRK/A", "BRK/B", "BRKR", "BRKRP", "BRLS", "BRLSW", "BRLT", "BRN", "BRNS", "BRO", "BROS", "BRR", "BRRWW", "BRSL", "BRSP", "BRT", "BRTX", "BRW", "BRX", "BRY", "BRZE", "BSAA", "BSAAU", "BSAC", "BSBK", "BSBR", "BSET", "BSL", "BSLK", "BSLKW", "BSM", "BSRR", "BST", "BSTZ", "BSVN", "BSX", "BSY", "BTA", "BTAI", "BTBD", "BTBDW", "BTBT", "BTCS", "BTCT", "BTDR", "BTE", "BTG", "BTI", "BTM", "BTMD", "BTMWW", "BTO", "BTOC", "BTOG", "BTQ", "BTSG", "BTSGU", "BTT", "BTTC", "BTU", "BTX", "BTZ", "BUD", "BUI", "BULL", "BULLW", "BUR", "BURL", "BURU", "BUSE", "BUSEP", "BUUU", "BV", "BVFL", "BVN", "BVS", "BW", "BW^A", "BWA", "BWAY", "BWB", "BWBBP", "BWEN", "BWFG", "BWG", "BWIN", "BWLP", "BWMN", "BWMX", "BWNB", "BWSN", "BWXT", "BX", "BXC", "BXMT", "BXMX", "BXP", "BXSL", "BY", "BYAH", "BYD", "BYFC", "BYM", "BYND", "BYRN", "BYSI", "BZ", "BZAI", "BZAIW", "BZFD", "BZFDW", "BZH", "BZUN", "C", "C^N", "CAAP", "CAAS", "CABA", "CABO", "CABR", "CAC", "CACC", "CACI", "CADE", "CADE^A", "CADL", "CAE", "CAEP", "CAF", "CAG", "CAH", "CAI", "CAKE", "CAL", "CALC", "CALM", "CALX", "CAMP", "CAMT", "CAN", "CANF", "CANG", "CAPL", "CAPN", "CAPNU", "CAPR", "CAPS", "CAPT", "CAPTW", "CAR", "CARE", "CARG", "CARL", "CARR", "CARS", "CART", "CARV", "CASH", "CASI", "CASS", "CASY", "CAT", "CATO", "CATX", "CATY", "CAVA", "CB", "CBAN", "CBAT", "CBFV", "CBIO", "CBK", "CBL", "CBLL", "CBNA", "CBNK", "CBOE", "CBRE", "CBRL", "CBSH", "CBT", "CBU", "CBUS", "CBZ", "CC", "CCAP", "CCB", "CCBG", "CCC", "CCCC", "CCCX", "CCCXU", "CCCXW", "CCD", "CCEC", "CCEL", "CCEP", "CCG", "CCHH", "CCI", "CCID", "CCIF", "CCII", "CCIIU", "CCIIW", "CCIX", "CCIXW", "CCJ", "CCK", "CCL", "CCLD", "CCLDO", "CCM", "CCNE", "CCNEP", "CCO", "CCOI", "CCRN", "CCS", "CCSI", "CCTG", "CCU", "CCZ", "CD", "CDE", "CDIO", "CDLR", "CDLX", "CDNA", "CDNS", "CDP", "CDR^B", "CDR^C", "CDRE", "CDRO", "CDROW", "CDT", "CDTG", "CDTTW", "CDTX", "CDW", "CDXS", "CDZI", "CDZIP", "CE", "CECO", "CEE", "CEG", "CELC", "CELH", "CELU", "CELUW", "CELZ", "CENN", "CENT", "CENTA", "CENX", "CEP", "CEPF", "CEPO", "CEPT", "CEPU", "CEPV", "CERS", "CERT", "CET", "CETX", "CETY", "CEV", "CEVA", "CF", "CFBK", "CFFI", "CFFN", "CFG", "CFG^E", "CFG^H", "CFG^I", "CFLT", "CFND", "CFR", "CFR^B", "CG", "CGABL", "CGAU", "CGBD", "CGBDL", "CGC", "CGCT", "CGCTW", "CGEM", "CGEN", "CGNT", "CGNX", "CGO", "CGON", "CGTL", "CGTX", "CHA", "CHAC", "CHACR", "CHACU", "CHAR", "CHARR", "CHCI", "CHCO", "CHCT", "CHD", "CHDN", "CHE", "CHEC", "CHECU", "CHECW", "CHEF", "CHEK", "CHGG", "CHH", "CHI", "CHKP", "CHMG", "CHMI", "CHMI^A", "CHMI^B", "CHNR", "CHOW", "CHPG", "CHPGR", "CHPGU", "CHPT", "CHR", "CHRD", "CHRS", "CHRW", "CHSCL", "CHSCM", "CHSCN", "CHSCO", "CHSCP", "CHSN", "CHT", "CHTR", "CHW", "CHWY", "CHY", "CHYM", "CI", "CIA", "CIB", "CICB", "CIEN", "CIF", "CIFR", "CIFRW", "CIG", "CIGI", "CIGL", "CII", "CIIT", "CIK", "CIM", "CIM^A", "CIM^B", "CIM^C", "CIM^D", "CIMN", "CIMO", "CIMP", "CINF", "CING", "CINGW", "CINT", "CIO", "CIO^A", "CION", "CISO", "CISS", "CIVB", "CIVI", "CIX", "CJET", "CJMB", "CKX", "CL", "CLAR", "CLB", "CLBK", "CLBT", "CLCO", "CLDI", "CLDT", "CLDT^A", "CLDX", "CLF", "CLFD", "CLGN", "CLH", "CLIK", "CLIR", "CLLS", "CLM", "CLMB", "CLMT", "CLNE", "CLNN", "CLNNW", "CLOV", "CLPR", "CLPS", "CLPT", "CLRB", "CLRO", "CLS", "CLSD", "CLSK", "CLSKW", "CLST", "CLVT", "CLW", "CLWT", "CLX", "CLYM", "CM", "CMA", "CMA^B", "CMBM", "CMBT", "CMC", "CMCL", "CMCM", "CMCO", "CMCSA", "CMCT", "CMDB", "CME", "CMG", "CMI", "CMMB", "CMND", "CMP", "CMPO", "CMPOW", "CMPR", "CMPS", "CMPX", "CMRC", "CMRE", "CMRE^B", "CMRE^C", "CMRE^D", "CMS", "CMS^B", "CMS^C", "CMSA", "CMSC", "CMSD", "CMT", "CMTG", "CMTL", "CMU", "CNA", "CNC", "CNCK", "CNCKW", "CNDT", "CNET", "CNEY", "CNF", "CNH", "CNI", "CNK", "CNL", "CNM", "CNMD", "CNNE", "CNO", "CNO^A", "CNOB", "CNOBP", "CNP", "CNQ", "CNR", "CNS", "CNSP", "CNTA", "CNTB", "CNTX", "CNTY", "CNVS", "CNX", "CNXC", "CNXN", "COCH", "COCHW", "COCO", "COCP", "CODA", "CODI", "CODI^A", "CODI^B", "CODI^C", "CODX", "COE", "COEP", "COEPW", "COF", "COF^I", "COF^J", "COF^K", "COF^L", "COF^N", "COFS", "COGT", "COHN", "COHR", "COHU", "COIN", "COKE", "COLA", "COLAR", "COLAU", "COLB", "COLD", "COLL", "COLM", "COMM", "COMP", "CON", "COO", "COOK", "COOT", "COOTW", "COP", "COPL", "COR", "CORT", "CORZ", "CORZW", "CORZZ", "COSM", 
       #    "COSO", "COST", "COTY", "COUR", "COYA", "CP", "CPA", "CPAC", "CPAY", "CPB", "CPBI", "CPF", "CPHC", "CPHI", "CPIX", "CPK", "CPNG", "CPOP", "CPRI", "CPRT", "CPRX", "CPS", "CPSH", "CPSS", "CPT", "CPZ", "CQP", "CR", "CRACU", "CRAI", "CRAQ", "CRAQR", "CRBD", "CRBG", "CRBP", "CRBU", "CRC", "CRCL", "CRCT", "CRD/A", "CRD/B", "CRDF", "CRDL", "CRDO", "CRE", "CREG", "CRESW", "CRESY", "CREV", "CREVW", "CREX", "CRF", "CRGO", "CRGOW", "CRGY", "CRH", "CRI", "CRIS", "CRK", "CRL", "CRM", "CRMD", "CRML", "CRMLW", "CRMT", "CRNC", "CRNT", "CRNX", "CROX", "CRS", "CRSP", "CRSR", "CRT", "CRTO", "CRUS", "CRVL", "CRVO", "CRVS", "CRWD", "CRWS", "CRWV", "CSAI", "CSAN", "CSBR", "CSCO", "CSGP", "CSGS", "CSIQ", "CSL", "CSPI", "CSQ", "CSR", "CSTE", "CSTL", "CSTM", "CSV", "CSW", "CSWC", "CSX", "CTA^A", "CTA^B", "CTAS", "CTBB", "CTBI", "CTDD", "CTEV", "CTGO", "CTKB", "CTLP", "CTM", "CTMX", "CTNM", "CTNT", "CTO", "CTO^A", "CTOR", "CTOS", "CTRA", "CTRE", "CTRI", "CTRM", "CTRN", "CTS", "CTSH", "CTSO", "CTVA", "CTW", "CTXR", "CUB", "CUBB", "CUBE", "CUBI", "CUBI^F", "CUBWU", "CUBWW", "CUE", "CUK", "CULP", "CUPR", "CURB", "CURI", "CURR", "CURV", "CURX", "CUZ", "CV", "CVAC", "CVBF", "CVCO", "CVE", "CVEO", "CVGI", "CVGW", "CVI", "CVKD", "CVLG", "CVLT", "CVM", "CVNA", "CVR", "CVRX", "CVS", "CVU", "CVV", "CVX", "CW", "CWAN", "CWBC", "CWCO", "CWD", "CWEN", "CWH", "CWK", "CWST", "CWT", "CX", "CXAI", "CXAIW", "CXDO", "CXE", "CXH", "CXM", "CXT", "CXW", "CYBN", "CYBR", "CYCN", "CYCU", "CYCUW", "CYD", "CYH", "CYN", "CYPH", "CYRX", "CYTK", "CZFS", "CZNC", "CZR", "CZWI", "D", "DAAQ", "DAAQU", "DAAQW", "DAC", "DAIC", "DAICW", "DAIO", "DAKT", "DAL", "DAN", "DAO", "DAR", "DARE", "DASH", "DAVA", "DAVE", "DAVEW", "DAWN", "DAY", "DB", "DBD", "DBGI", "DBI", "DBL", "DBRG", "DBRG^H", "DBRG^I", "DBRG^J", "DBVT", "DBX", "DC", "DCBO", "DCGO", "DCI", "DCO", "DCOM", "DCOMG", "DCOMP", "DCTH", "DD", "DDC", "DDD", "DDI", "DDL", "DDOG", "DDS", "DDT", "DE", "DEA", "DEC", "DECK", "DEFT", "DEI", "DELL", "DENN", "DEO", "DERM", "DEVS", "DFDV", "DFDVW", "DFH", "DFIN", "DFLI", "DFLIW", "DFP", "DFSC", "DFSCW", "DG", "DGICA", "DGICB", "DGII", "DGLY", "DGNX", "DGX", "DGXX", "DH", "DHC", "DHCNI", "DHCNL", "DHF", "DHI", "DHIL", "DHR", "DHT", "DHX", "DHY", "DIAX", "DIBS", "DIN", "DINO", "DIOD", "DIS", "DIT", "DJCO", "DJT", "DJTWW", "DK", "DKI", "DKL", "DKNG", "DKS", "DLB", "DLHC", "DLNG", "DLNG^A", "DLO", "DLPN", "DLR", "DLR^J", "DLR^K", "DLR^L", "DLTH", "DLTR", "DLX", "DLXY", "DLY", "DMA", "DMAA", "DMAAR", "DMAAU", "DMAC", "DMB", "DMIIU", "DMLP", "DMO", "DMRC", "DNA", "DNLI", "DNMXU", "DNN", "DNOW", "DNP", "DNTH", "DNUT", "DOC", "DOCN", "DOCS", "DOCU", "DOGZ", "DOLE", "DOMH", "DOMO", "DOOO", "DORM", "DOUG", "DOV", "DOW", "DOX", "DOYU", "DPG", "DPRO", "DPZ", "DQ", "DRCT", "DRD", "DRDB", "DRDBW", "DRH", "DRH^A", "DRI", "DRIO", "DRMA", "DRS", "DRTS", "DRTSW", "DRUG", "DRVN", "DSGN", "DSGR", "DSGX", "DSL", "DSM", "DSP", "DSS", "DSU", "DSWL", "DSX", "DSX^B", "DSY", "DSYWW", "DT", "DTB", "DTCK", "DTE", "DTF", "DTG", "DTI", "DTIL", "DTK", "DTM", "DTSQ", "DTSQR", "DTSQU", "DTSS", "DTST", "DTSTW", "DTW", "DUK", "DUK^A", "DUKB", "DUO", "DUOL", "DUOT", "DV", "DVA", "DVAX", "DVLT", "DVN", "DVS", "DWSN", "DWTX", "DX", "DX^C", "DXC", "DXCM", "DXF", "DXLG", "DXPE", "DXR", "DXST", "DXYZ", "DY", "DYAI", "DYCQ", "DYCQR", "DYN", "DYORU", "E", "EA", "EAD", "EAF", "EAI", "EARN", "EAT", "EB", "EBAY", "EBC", "EBF", "EBMT", "EBON", "EBS", "EC", "ECAT", "ECBK", "ECC ", "ECC^D", "ECCC", "ECCF", "ECCU", "ECCV", "ECCW", "ECCX", "ECDA", "ECDAW", "ECF", "ECF^A", "ECG", "ECL", "ECO", "ECOR", "ECPG", "ECVT", "ECX", "ECXWW", "ED", "EDAP", "EDBL", "EDBLW", "EDD", "EDF", "EDHL", "EDIT", "EDN", "EDRY", "EDSA", "EDTK", "EDU", "EDUC", "EE", "EEA", "EEFT", "EEIQ", "EEX", "EFC", "EFC^A", "EFC^B", "EFC^C", "EFC^D", "EFOI", "EFR", "EFSC", "EFSCP", "EFSI", "EFT", "EFX", "EFXT", "EG", "EGAN", "EGBN", "EGG", "EGHA", "EGHAR", "EGHT", "EGY", "EH", "EHAB", "EHC", "EHGO", "EHI", "EHLD", "EHTH", "EIC", "EICA", "EICB", "EICC", "EIG", "EIIA", "EIM", "EIX", "EJH", "EKSO", "EL", "ELA", "ELAB", "ELAN", "ELBM", "ELC", "ELDN", "ELF", "ELLO", "ELMD", "ELME", "ELOG", "ELP", "ELPC", "ELPW", "ELS", "ELSE", "ELTK", "ELTX", "ELUT", "ELV", "ELVA", "ELVN", "ELVR", "ELWS", "ELWT", "EM", "EMA", "EMBC", "EMBJ", "EMD", "EME", "EMF", "EMIS", "EMISR", "EML", "EMN", "EMO", "EMP", "EMPD", "EMR", "ENB", "ENGN", "ENGNW", "ENGS", "ENIC", "ENJ", "ENLT", "ENLV", "ENO", "ENOV", "ENPH", "ENR", "ENS", "ENSC", "ENSG", "ENTA", "ENTG", "ENTO", "ENTX", "ENVA", "ENVB", "ENVX", "EOD", "EOG", "EOI", "EOLS", "EONR", "EOS", "EOSE", "EOSEW", "EOT", "EP", "EP^C", "EPAC", "EPAM", "EPC", "EPD", "EPM", "EPOW", "EPR", "EPR^C", "EPR^E", "EPR^G", "EPRT", "EPRX", "EPSM", "EPSN", "EPWK", "EQ", "EQBK", "EQH", "EQH^A", "EQH^C", "EQIX", "EQNR", "EQR", "EQS", "EQT", "EQX", "ERAS", "ERC", "ERH", "ERIC", "ERIE", "ERII", "ERNA", "ERO", "ES", "ESAB", "ESCA", "ESE", "ESEA", "ESGL", "ESHAR", "ESI", "ESLA", "ESLAW", "ESLT", "ESNT", "ESOA", "ESP", "ESPR", "ESQ", "ESRT", "ESS", "ESTA", "ESTC", "ET", "ET^I", "ETB", "ETD", "ETG", "ETHM", "ETHMU", "ETHMW", "ETHZ", "ETI^", "ETJ", "ETN", "ETO", "ETON", "ETOR", "ETR", "ETS", "ETSY", "ETV", "ETW", "ETX ", "ETY", "EU", "EUDA", "EUDAW", "EURK", "EURKR", "EVAC", "EVAX", "EVC", "EVCM", "EVER", "EVEX", "EVF", "EVG", "EVGN", "EVGO", "EVGOW", "EVH", "EVI", "EVLV", "EVLVW", "EVMN", "EVN", "EVO", "EVOK", "EVOXU", "EVR", "EVRG", "EVT", "EVTC", "EVTL", "EVTV", "EVV", "EW", "EWBC", "EWCZ", "EWTX", "EXAS", "EXC", "EXE", "EXEEL", "EXEL", "EXFY", "EXG", "EXK", "EXLS", "EXOD", "EXOZ", "EXP", "EXPD", "EXPE", "EXPI", "EXPO", "EXR", "EXTR", "EYE", "EYPT", "EZGO", "EZPW", "F", "F^B", "F^C", "F^D", "FA", "FACT", "FACTW", "FAF", "FAMI", "FANG", "FARM", "FAST", "FAT", "FATBB", "FATBP", "FATE", "FATN", "FAX", "FBGL", "FBIN", "FBIO", "FBIOP", "FBIZ", "FBK", "FBLA", "FBLG", "FBNC", "FBP", "FBRT", "FBRT^E", "FBRX", "FBYD", "FBYDW", "FC", "FCAP", "FCBC", "FCCO", "FCEL", "FCF", "FCFS", "FCHL", "FCN", "FCNCA", "FCNCO", "FCNCP", "FCO", "FCPT", "FCRX", "FCT", "FCUV", "FCX", "FDBC", "FDMT", "FDP", "FDS", "FDSB", "FDUS", "FDX", "FE", "FEAM", "FEBO", "FEDU", "FEIM", "FELE", "FEMY", "FENC", "FENG", "FER", "FERA", "FERAR", "FERG", "FET", "FF", "FFA", "FFAI", "FFAIW", "FFBC", "FFC", "FFIC", "FFIN", "FFIV", "FFWM", "FG", "FGBI", "FGBIP", "FGEN", "FGI", "FGIWW", "FGL", "FGMC", "FGMCR", "FGMCU", "FGN", "FGNX", "FGNXP", "FGSN", "FHB", "FHI", "FHN", "FHN^C", "FHN^E", "FHN^F", "FHTX", "FIBK", "FICO", "FIEE", "FIG", "FIGR", "FIGS", "FIGX", "FIGXU", "FIGXW", "FIHL", "FINS", "FINV", "FINW", "FIP", "FIS", "FISI", "FISV", "FITB", "FITBI", "FITBO", "FITBP", "FIVE", "FIVN", "FIX", "FIZZ", "FKWL", "FLC", "FLD", "FLDDW", "FLEX", "FLG", "FLG^A", "FLG^U", "FLGC", "FLGT", "FLL", "FLNC", "FLNG", "FLNT", "FLO", "FLOC", "FLR", "FLS", "FLUT", "FLUX", "FLWS", "FLX", "FLXS", "FLY", "FLYE", "FLYW", "FLYX", "FMAO", "FMBH", "FMC", "FMFC", "FMN", "FMNB", "FMS", "FMST", "FMSTW", "FMX", "FMY", "FN", "FNB", "FND", "FNF", "FNGR", "FNKO", 
        #   "FNLC", "FNV", "FNWB", "FNWD", "FOA", "FOF", "FOFO", "FOLD", "FONR", "FOR", "FORA", "FORD", "FORM", "FORR", "FORTY", "FOSL", "FOSLL", "FOUR", "FOUR^A", "FOX", "FOXA", "FOXF", "FOXX", "FOXXW", "FPF", "FPH", "FPI", "FR", "FRA", "FRAF", "FRBA", "FRD", "FRGE", "FRGT", "FRHC", "FRME", "FRMEP", "FRMI", "FRO", "FROG", "FRPH", "FRPT", "FRSH", "FRST", "FRSX", "FRT", "FRT^C", "FSBC", "FSBW", "FSCO", "FSEA", "FSFG", "FSHP", "FSHPR", "FSI", "FSK", "FSLR", "FSLY", "FSM", "FSP", "FSS", "FSSL", "FSTR", "FSUN", "FSV", "FT", "FTAI", "FTAIM", "FTAIN", "FTCI", "FTDR", "FTEK", "FTEL", "FTF", "FTFT", "FTHM", "FTHY", "FTI", "FTK", "FTLF", "FTNT", "FTRE", "FTRK", "FTS", "FTV", "FTW", "FUBO", "FUFU", "FUFUW", "FUL", "FULC", "FULT", "FULTP", "FUN", "FUNC", "FUND", "FURY", "FUSB", "FUSE", "FUSEW", "FUTU", "FVCB", "FVN", "FVNNR", "FVR", "FVRR", "FWONA", "FWONK", "FWRD", "FWRG", "FXNC", "FYBR", "G", "GAB", "GAB^G", "GAB^H", "GAB^K", "GABC", "GAIA", "GAIN", "GAINI", "GAINL", "GAINN", "GAINZ", "GALT", "GAM", "GAM^B", "GAMB", "GAME", "GANX", "GAP", "GASS", "GATX", "GAU", "GAUZ", "GBAB", "GBCI", "GBDC", "GBFH", "GBIO", "GBLI", "GBR", "GBTG", "GBX", "GCBC", "GCI", "GCL", "GCMG", "GCMGW", "GCO", "GCT", "GCTK", "GCTS", "GCV", "GD", "GDC", "GDDY", "GDEN", "GDEV", "GDEVW", "GDHG", "GDL", "GDO", "GDOT", "GDRX", "GDS", "GDTC", "GDV", "GDV^H", "GDV^K", "GDYN", "GE", "GECC", "GECCG", "GECCH", "GECCI", "GECCO", "GEF", "GEG", "GEGGL", "GEHC", "GEL", "GELS", "GEMI", "GEN", "GENC", "GENI", "GENK", "GENVR", "GEO", "GEOS", "GERN", "GES", "GETY", "GEV", "GEVO", "GF", "GFAI", "GFAIW", "GFF", "GFI", "GFL", "GFR", "GFS", "GGAL", "GGB", "GGG", "GGN", "GGN^B", "GGR", "GGROW", "GGT", "GGT^E", "GGT^G", "GGZ", "GH", "GHC", "GHG", "GHI", "GHLD", "GHM", "GHRS", "GHY", "GIB", "GIBO", "GIC", "GIFI", "GIFT", "GIG", "GIGGU", "GIGGW", "GIGM", "GIII", "GIL", "GILD", "GILT", "GIPR", "GIPRW", "GIS", "GITS", "GIW", "GIWWR", "GIWWU", "GJH", "GJO", "GJS", "GJT", "GKOS", "GL", "GL^D", "GLAD", "GLBE", "GLBS", "GLBZ", "GLDD", "GLDG", "GLE", "GLIBA", "GLIBK", "GLMD", "GLNG", "GLO", "GLOB", "GLOP^A", "GLOP^B", "GLOP^C", "GLP", "GLP^B", "GLPG", "GLPI", "GLQ", "GLRE", "GLSI", "GLTO", "GLU", "GLU^B", "GLUE", "GLV", "GLW", "GLXG", "GLXY", "GM", "GMAB", "GME", "GMED", "GMGI", "GMHS", "GMM", "GMRE", "GMRE^A", "GNE", "GNFT", "GNK", "GNL", "GNL^A", "GNL^B", "GNL^D", "GNL^E", "GNLN", "GNLX", "GNPX", "GNRC", "GNS", "GNSS", "GNT", "GNT^A", "GNTA", "GNTX", "GNW", "GO", "GOCO", "GOF", "GOGO", "GOLF", "GOOD", "GOODN", "GOODO", "GOOG", "GOOGL", "GOOS", "GORO", "GORV", "GOSS", "GOTU", "GOVX", "GP", "GPAT", "GPATW", "GPC", "GPCR", "GPI", "GPJA", "GPK", "GPMT", "GPMT^A", "GPN", "GPOR", "GPRE", "GPRK", "GPRO", "GPUS", "GPUS^D", "GRAB", "GRABW", "GRAF", "GRAL", "GRAN", "GRBK", "GRBK^A", "GRC", "GRCE", "GRDN", "GREE", "GREEL", "GRF", "GRFS", "GRI", "GRMN", "GRND", "GRNQ", "GRNT", "GRO", "GROV", "GROW", "GROY", "GRPN", "GRRR", "GRRRW", "GRVY", "GRWG", "GRX", "GS", "GS^A", "GS^C", "GS^D", "GSAT", "GSBC", "GSBD", "GSHD", "GSHR", "GSHRW", "GSIT", "GSIW", "GSK", "GSL", "GSL^B", "GSM", "GSRF", "GSRFR", "GSRFU", "GSUN", "GT", "GTBP", "GTE", "GTEC", "GTEN", "GTENW", "GTERA", "GTERR", "GTERU", "GTERW", "GTES", "GTIM", "GTLB", "GTLS", "GTLS^B", "GTM", "GTN", "GTX", "GTY", "GUG", "GUT", "GUT^C", "GUTS", "GV", "GVA", "GVH", "GWAV", "GWH", "GWRE", "GWRS", "GWW", "GXAI", "GXO", "GYRE", "GYRO", "H", "HAE", "HAFC", "HAFN", "HAIN", "HAL", "HALO", "HAO", "HAS", "HASI", "HAVAU", "HAYW", "HBAN", "HBANL", "HBANM", "HBANP", "HBB", "HBCP", "HBI", "HBIO", "HBM", "HBNB", "HBNC", "HBR", "HBT", "HCA", "HCAI", "HCAT", "HCC", "HCHL", "HCI", "HCKT", "HCM", "HCMA", "HCMAU", "HCMAW", "HCSG", "HCTI", "HCWB", "HCWC", "HCXY", "HD", "HDB", "HDL", "HDSN", "HE", "HEI", "HEI/A", "HELE", "HEPS", "HEQ", "HERE", "HERZ", "HESM", "HFBL", "HFFG", "HFRO", "HFRO^A", "HFRO^B", "HFWA", "HG", "HGBL", "HGLB", "HGTY", "HGV", "HHH", "HHS", "HI", "HIFS", "HIG", "HIG^G", "HIHO", "HII", "HIMS", "HIMX", "HIND", "HIO", "HIPO", "HIT", "HITI", "HIVE", "HIW", "HIX", "HKD", "HKIT", "HKPD", "HL", "HL^B", "HLF", "HLI", "HLIO", "HLIT", "HLLY", "HLMN", "HLN", "HLNE", "HLP", "HLT", "HLX", "HMC", "HMN", "HMR", "HMY", "HNGE", "HNI", "HNNA", "HNNAZ", "HNRG", "HNST", "HNVR", "HOFT", "HOG", "HOLO", "HOLOW", "HOLX", "HOMB", "HON", "HOOD", "HOPE", "HOTH", "HOUR", "HOUS", "HOV", "HOVNP", "HOVR", "HOVRW", "HOWL", "HP", "HPAI", "HPAIW", "HPE", "HPE^C", "HPF", "HPI", "HPK", "HPP", "HPP^C", "HPQ", "HPS", "HQH", "HQI", "HQL", "HQY", "HR", "HRB", "HRI", "HRL", "HRMY", "HROW", "HRTG", "HRTX", "HRZN", "HSAI", "HSBC", "HSCS", "HSCSW", "HSDT", "HSHP", "HSIC", "HSII", "HSPO", "HSPOU", "HSPOW", "HSPT", "HSPTU", "HST", "HSTM", "HSY", "HTB", "HTBK", "HTCO", "HTCR", "HTD", "HTFB", "HTFC", "HTFL", "HTGC", "HTH", "HTHT", "HTLD", "HTLM", "HTO", "HTOO", "HTOOW", "HTZ", "HTZWW", "HUBB", "HUBC", "HUBCW", "HUBCZ", "HUBG", "HUBS", "HUDI", "HUHU", "HUIZ", "HUM", "HUMA", "HUMAW", "HUN", "HURA", "HURC", "HURN", "HUSA", "HUT", "HUYA", "HVII", "HVIIR", "HVIIU", "HVMC", "HVMCW", "HVT", "HVT/A", "HWBK", "HWC", "HWCPZ", "HWH", "HWKN", "HWM", "HWM^", "HXHX", "HXL", "HY", "HYAC", "HYFM", "HYFT", "HYI", "HYLN",
         #  "HYMC", "HYPD", "HYPR", "HYT", "HZO", "IAC", "IAE", "IAF", "IAG", "IART", "IAS", "IAUX", "IBAC", "IBCP", "IBEX", "IBG", "IBIO", "IBKR", "IBM", "IBN", "IBO", "IBOC", "IBP", "IBRX", "IBTA", "ICCC", "ICCM", "ICE", "ICFI", "ICG", "ICHR", "ICL", "ICLR", "ICMB", "ICON", "ICR^A", "ICU", "ICUCW", "ICUI", "IDA", "IDAI", "IDCC", "IDE", "IDN", "IDR", "IDT", "IDXX", "IDYA", "IE", "IEP", "IESC", "IEX", "IFBD", "IFF", "IFN", "IFRX", "IFS", "IGA", "IGC", "IGD", "IGI", "IGIC", "IGR", "IH", "IHD", "IHG", "IHRT", "IHS", "IHT", "IIF", "III", "IIIN", "IIIV", "IIM", "IINN", "IINNW", "IIPR", "IIPR^A", "IKT", "ILAG", "ILLR", "ILLRW", "ILMN", "ILPT", "IMA", "IMAX", "IMCC", "IMCR", "IMDX", "IMG", "IMKTA", "IMMP", "IMMR", "IMMX", "IMNM", "IMNN", "IMO", "IMOS", "IMPP", "IMPPP", "IMRN", "IMRX", "IMSR", "IMSRW", "IMTE", "IMTX", "IMUX", "IMVT", "IMXI", "INAB", "INAC", "INACR", "INACU", "INBK", "INBKZ", "INBS", "INBX", "INCR", "INCY", "INDB", "INDI", "INDO", "INDP", "INDV", "INEO", "INFA", "INFU", "INFY", "ING", "INGM", "INGN", "INGR", "INHD", "INKT", "INLF", "INLX", "INM", "INMB", "INMD", "INN", "INN^E", "INN^F", "INNV", "INO", "INOD", "INR", "INSE", "INSG", "INSM", "INSP", "INSW", "INTA", "INTC", "INTG", "INTJ", "INTR", "INTS", "INTT", "INTU", "INTZ", "INUV", "INV", "INVA", "INVE", "INVH", "INVX", "INVZ", "INVZW", "IOBT", "IONQ", "IONR", "IONS", "IOR", "IOSP", "IOT", "IOTR", "IOVA", "IP", "IPAR", "IPCX", "IPCXR", "IPCXU", "IPDN", "IPG", "IPGP", "IPHA", "IPI", "IPM", "IPOD", "IPODW", "IPSC", "IPST", "IPW", "IPWR", "IPX", "IQ", "IQI", "IQST", "IQV", "IR", "IRBT", "IRD", "IRDM", "IREN", "IRIX", "IRM", "IRMD", "IRON", "IROQ", "IRS", "IRT", "IRTC", "IRWD", "ISBA", "ISD", "ISOU", "ISPC", "ISPO", "ISPOW", "ISPR", "ISRG", "ISRL", "ISRLW", "ISSC", "ISTR", "IT", "ITGR", "ITIC", "ITP", "ITRG", "ITRI", "ITRM", "ITRN", "ITT", "ITUB", "ITW", "IVA", "IVDA", "IVDAW", "IVF", "IVP", "IVR", "IVR^C", "IVT", "IVVD", "IVZ", "IX", "IXHL", "IZEA", "IZM", "J", "JACK", "JACS", "JAGX", "JAKK", "JAMF", "JANX", "JAZZ", "JBDI", "JBGS", "JBHT", "JBI", "JBIO", "JBK", "JBL", "JBLU", "JBS", "JBSS", "JBTM", "JCAP", "JCE", "JCI", "JCSE", "JCTC", "JD", "JDZG", "JEF", "JELD", "JEM", "JENA", "JFB", "JFBR", "JFBRW", "JFIN", "JFR", "JFU", "JG", "JGH", "JHG", "JHI", "JHS", "JHX", "JILL", "JJSF", "JKHY", "JKS", "JL", "JLHL", "JLL", "JLS", "JMIA", "JMM", "JMSB", "JNJ", "JOB", "JOBY", "JOE", "JOF", "JOUT", "JOYY", "JPC", "JPM", "JPM^C", "JPM^D", "JPM^J", "JPM^K", "JPM^L", "JPM^M", "JQC", "JRI", "JRS", "JRSH", "JRVR", "JSM", "JSPR", "JSPRW", "JTAI", "JUNS", "JVA", "JWEL", "JXG", "JXN", "JXN^A", "JYD", "JYNT", "JZ", "JZXN", "K", "KAI", "KALA", "KALU", "KALV", "KAPA", "KAR", "KARO", "KAVL", "KB", "KBDC", "KBH", "KBR", "KBSX", "KC", "KCHV", "KCHVR", "KCHVU", "KD", "KDK", "KDKRW", "KDP", "KE", "KELYA", "KELYB", "KEN", "KEP", "KEQU", "KEX", "KEY", "KEY^I", "KEY^J", "KEY^K", "KEY^L", "KEYS", "KF", "KFFB", "KFII", "KFIIR", "KFRC", "KFS", "KFY", "KG", "KGC", "KGEI", "KGS", "KHC", "KIDS", "KIDZ", "KIDZW", "KIM", "KIM^L", "KIM^M", "KIM^N", "KINS", "KIO", "KITT", "KITTW", "KKR", "KKR^D", "KKRS", "KKRT", "KLAC", "KLAR", "KLC", "KLIC", "KLRS", "KLTO", "KLTOW", "KLTR", "KLXE", "KMB", "KMDA", "KMI", "KMPB", "KMPR", "KMRK", "KMT", "KMTS", "KMX", "KN", "KNDI", "KNF", "KNOP", "KNRX", "KNSA", "KNSL", "KNTK", "KNX", "KO", "KOD", "KODK", "KOF", "KOP", "KOPN", "KORE", "KOS", "KOSS", "KOYN", "KOYNU", "KOYNW", "KPLT", "KPLTW", "KPRX", "KPTI", "KR", "KRC", "KREF", "KREF^A", "KRG", "KRKR", "KRMD", "KRMN", "KRNT", "KRNY", "KRO", "KROS", "KRP", "KRRO", "KRT", "KRUS", "KRYS", "KSCP", "KSPI", "KSS", "KT", "KTB", "KTCC", "KTF", "KTH", "KTN", "KTOS", "KTTA", "KTTAW", "KULR", "KURA", "KVAC", "KVACW", "KVHI", "KVUE", "KVYO", "KW", "KWM", "KWMWW", "KWR", "KXIN", "KYIV", "KYIVW", "KYMR", "KYN", "KYTX", "KZIA", "KZR", "L", "LAB", "LAC", "LAD", "LADR", "LAES", "LAFAU", "LAKE", "LAMR", "LAND", "LANDM", "LANDO", "LANDP", "LANV", "LAR", "LARK", "LASE", "LASR", "LATA", "LATAU", "LATAW", "LAUR", "LAW", "LAZ", "LAZR", "LB", "LBGJ", "LBRDA", "LBRDK", "LBRDP", "LBRT", "LBRX", "LBTYA", "LBTYB", "LBTYK", "LC", "LCCC", "LCCCR", "LCFY", "LCFYW", "LCID", "LCII", "LCNB", "LCTX", "LCUT", "LDI", "LDOS", "LDP", "LDWY", "LE", "LEA", "LECO", "LEDS", "LEE", "LEG", "LEGH", "LEGN", "LEGT", "LEN", "LENZ", "LEO", "LESL", "LEU", "LEVI", "LEXX", "LEXXW", "LFCR", "LFMD", "LFMDP", "LFS", "LFST", "LFT", "LFT^A", "LFUS", "LFVN", "LFWD", "LGCB", "LGCL", "LGCY", "LGHL", "LGI", "LGIH", "LGL", "LGN", "LGND", "LGO", "LGPS", "LGVN", "LH", "LHAI", "LHSW", "LHX", "LI", "LICN", "LIDR", "LIDRW", "LIEN", "LIF", "LII", "LILA", "LILAK", "LIMN", "LIN", "LINC", "LIND", "LINE", "LINK", "LION", "LIQT", "LITB", "LITE", "LITM", "LITS", "LIVE", "LIVN", "LIXT", "LIXTW", "LLY", "LLYVA", "LLYVK", "LMAT", "LMB", "LMFA", "LMND", "LMNR", "LMT", "LNAI", "LNC", "LNC^D", "LND", "LNG", "LNKB", "LNKS", "LNN", "LNSR", "LNT", "LNTH", "LNZA", "LNZAW", "LOAN", "LOAR", "LOB", "LOB^A", "LOBO", "LOCL", "LOCO", "LODE", "LOGI", "LOKV", "LOKVU", "LOKVW", "LOMA", "LOOP", "LOPE", "LOT", "LOTWW", "LOVE", "LOW", "LPA", "LPAA", "LPAAW", "LPBB", "LPBBW", "LPCN", "LPG", "LPL", "LPLA", "LPRO", "LPSN", "LPTH", "LPX", "LQDA", "LQDT", "LRCX", "LRE", "LRHC", "LRMR", "LRN", "LSAK", "LSBK", "LSCC", "LSE", "LSF", "LSH", "LSPD", "LSTA", "LSTR", "LTBR", "LTC", "LTCC", "LTH", "LTM", "LTRN", "LTRX", "LTRYW", "LU", "LUCD", "LUCK", "LUCY", "LUCYW", "LUD", "LULU", "LUMN", "LUNG", "LUNR", "LUV", "LUXE", "LVLU", "LVO", "LVRO", "LVROW", "LVS", "LVTX", "LVWR", "LW", "LWAC", "LWACU", "LWACW", "LWAY", "LWLG", "LX", "LXEH", "LXEO", "LXFR", "LXP", "LXP^C", "LXRX", "LXU", "LYB", "LYEL", "LYFT", "LYG", "LYRA", "LYTS", "LYV", "LZ", "LZB", "LZM", "LZMH", "M", "MA", "MAA", "MAA^I", "MAAS", "MAC", "MACI", "MACIW", "MAGH", "MAGN", "MAIA", "MAIN", "MAMA", "MAMK", "MAMO", "MAN", "MANH", "MANU", "MAPS", "MAPSW", "MAR", "MARA", "MARPS", "MAS", "MASI", "MASK", "MASS", "MAT", "MATH", "MATV", "MATW", "MATX", "MAX", "MAXN", "MAYA", "MAYAR", "MAYS", "MAZE", "MB", "MBAV", "MBAVW", "MBBC", "MBC", "MBCN", "MBI", "MBIN", "MBINL", "MBINM", "MBINN", "MBIO", "MBLY", "MBNKO", "MBOT", "MBRX", "MBUU", "MBVI", "MBVIU", "MBVIW", "MBWM", "MBX", "MC", "MCB", "MCBS", "MCD", "MCFT", "MCGA", "MCGAU", "MCGAW", "MCHB", "MCHP", "MCHPP", "MCHX", "MCI", "MCK", "MCN", "MCO", "MCR", "MCRB", "MCRI", "MCRP", "MCS", "MCTR", "MCW", "MCY", "MD", "MDAI", "MDAIW", "MDB", "MDBH", "MDCX", "MDCXW", "MDGL", "MDIA", "MDLZ", "MDRR", "MDT", "MDU", "MDV", "MDV^A", "MDWD", "MDXG", "MDXH", "MEC", "MED", "MEDP", "MEG", "MEGI", "MEGL", "MEHA", "MEI", "MELI", "MENS", "MEOH", "MER^K", "MERC", "MESA", "MESO", "MET", "MET^A", "MET^E", "MET^F", "META", "METC", "METCB", "METCI", "METCZ", "MFA", "MFA^B", "MFA^C", "MFAN", "MFAO", "MFC", "MFG", "MFI", "MFIC", "MFICL", "MFIN", "MFM", "MG", "MGA", "MGEE", "MGF", "MGIC", "MGIH", "MGLD", "MGM", "MGN", "MGNI", "MGNX", "MGPI", "MGR", "MGRB", "MGRC", "MGRD", "MGRE", "MGRT", "MGRX", "MGTX", "MGX", "MGY", "MGYR", "MH", "MHD", "MHF", "MHH", "MHK", "MHLA",
          # "AMGN","AMZN","CRM","CVX","DIS","GS","HD","IBM","JNJ","JPM","MCD","MMM","MRK","NKE","PG","TRV","UNH","VZ","WMT","V","KO","SHW","AXP","BA","CAT","CSCO","AAPL","HON","MSFT","NVDA",
           #"A","AAPL","ABBV","ABNB","ABT","ACGL","ACN","ADBE","ADI","ADM","ADP","ADSK","AEE","AEP","AES","AFL","AIG","AIZ","AJG","AKAM","ALB","ALGN","ALL","ALLE","AMAT","AMCR","AMD","AME","AMGN","AMP","AMT","AMZN","ANET","AON","AOS","APA","APD","APH","APO","APP","APTV","ARE","ATO","AVB","AVGO","AVY","AWK","AXON","AXP","AZO","BA","BAC","BALL","BAX","BBY","BDX","BEN","BF.B","BG","BIIB","BK","BKNG","BKR","BLDR","BLK","BMY","BR","BRK.B","BRO","BSX","BX","BXP","C","CAG","CAH","CARR","CAT","CB","CBOE","CBRE","CCI","CCL","CDNS","CDW","CEG","CF","CFG","CHD","CHRW","CHTR","CI","CINF","CL","CLX","CMCSA","CME","CMG","CMI","CMS","CNC","CNP","COF","COIN","COO","COP","COR","COST","CPAY","CPB","CPRT","CPT","CRL","CRM","CRWD","CSCO","CSGP","CSX","CTAS","CTRA","CTSH","CTVA","CVS","CVX","D","DAL","DASH","DAY","DD","DDOG","DE","DECK","DELL","DG","DGX","DHI","DHR","DIS","DLR","DLTR","DOC","DOV","DOW","DPZ","DRI","DTE","DUK","DVA","DVN","DXCM","EA","EBAY","ECL","ED","EFX","EG","EIX","EL","ELV","EME","EMR","EOG","EPAM","EQIX","EQR","EQT","ERIE","ES","ESS","ETN","ETR","EVRG","EW","EXC","EXE","EXPD","EXPE","EXR","F","FANG","FAST","FCX","FDS","FDX","FE","FFIV","FISV","FICO","FIS","FITB","FOX","FOXA","FRT","FSLR","FTNT","FTV","GD","GDDY","GE","GEHC","GEN","GEV","GILD","GIS","GL","GLW","GM","GNRC","GOOG","GOOGL","GPC","GPN","GRMN","GS","GWW","HAL","HAS","HBAN","HCA","HD","HIG","HII","HLT","HOLX","HON","HOOD","HPE","HPQ","HRL","HSIC","HST","HSY","HUBB","HUM","HWM","IBKR","IBM","ICE","IDXX","IEX","IFF","INCY","INTC","INTU","INVH","IP","IPG","IQV","IR","IRM","ISRG","IT","ITW","IVZ","J","JBHT","JBL","JCI","JKHY","JNJ","JPM","K","KDP","KEY","KEYS","KHC","KIM","KKR","KLAC","KMB","KMI","KO","KR","KVUE","L","LDOS","LEN","LH","LHX","LII","LIN","LKQ","LLY","LMT","LNT","LOW","LRCX","LULU","LUV","LVS","LW","LYB","LYV","MA","MAA","MAR","MAS","MCD","MCHP","MCK","MCO","MDLZ","MDT","MET","META","MGM","MHK","MKC","MLM","MMC","MMM","MNST","MO","MOH","MOS","MPC","MPWR","MRK","MRNA","MS","MSCI","MSFT","MSI","MTB","MTCH","MTD","MU","NCLH","NDAQ","NDSN","NEE","NEM","NFLX","NI","NKE","NOC","NOW","NRG","NSC","NTAP","NTRS","NUE","NVDA","NVR","NWS","NWSA","NXPI","O","ODFL","OKE","OMC","ON","ORCL","ORLY","OTIS","OXY","PANW","PAYC","PAYX","PCAR","PCG","PEG","PEP","PFE","PFG","PG","PGR","PH","PHM","PKG","PLD","PLTR","PM","PNC","PNR","PNW","PODD","POOL","PPG","PPL","PRU","PSA","PSKY","PSX","PTC","PWR","PYPL","Q","QCOM","RCL","REG","REGN","RF","RJF","RL","RMD","ROK","ROL","ROP","ROST","RSG","RTX","RVTY","SBAC","SBUX","SCHW","SHW","SJM","SLB","SMCI","SNA","SNPS","SO","SOLS","SOLV","SPG","SPGI","SRE","STE","STLD","STT","STX","STZ","SW","SWK","SWKS","SYF","SYK","SYY","T","TAP","TDG","TDY","TECH","TEL","TER","TFC","TGT","TJX","TKO","TMO","TMUS","TPL","TPR","TRGP","TRMB","TROW","TRV","TSCO","TSLA","TSN","TT","TTD","TTWO","TXN","TXT","TYL","UAL","UBER","UDR","UHS","ULTA","UNH","UNP","UPS","URI","USB","V","VICI","VLO","VLTO","VMC","VRSK","VRSN","VRTX","VST","VTR","VTRS","VZ","WAB","WAT","WBD","WDAY","WDC","WEC","WELL","WFC","WM","WMB","WMT","WRB","WSM","WST","WTW","WY","WYNN","XEL","XOM","XYL","XYZ","YUM","ZBH","ZBRA","ZTS"

#US100
"A", "AA", "AACB", "AACBR", "AACBU", "AACG", "AAL", "AAM", "AAME", "AAMI", "AAOI", "AAON", "AAP", "AAPG", "AAPL", "AARD", "AAT", "AAUC", "AB", "ABAT", "ABBV", "ABCB", "ABCL", "ABEO", "ABEV", "ABG", "ABL", "ABLLL", "ABLV", "ABLVW", "ABM", "ABNB", "ABOS", "ABP", "ABPWW", "ABR", "ABR^D", "ABR^E", "ABR^F", "ABSI", "ABT", "ABTC", "ABTS", "ABUS", "ABVC", "ABVE", "ABVEW", "ABVX", "ACA", "ACAD", "ACB", "ACCL", "ACCO", "ACCS", "ACDC", "ACEL", "ACET", "ACFN", "ACGL", "ACGLN", "ACGLO", "ACHC", "ACHR", "ACHV", "ACI", "ACIC", "ACIU", "ACIW", "ACLS", "ACLX", "ACM", "ACMR", "ACN", "ACNB", "ACNT", "ACOG", "ACON", "ACONW", "ACP", "ACP^A", "ACR", "ACR^C", "ACR^D", "ACRE", "ACRS", "ACRV", "ACT", "ACTG", "ACTU", "ACU", "ACV", "ACVA", "ACXP", "AD", "ADAG", "ADAM", "ADAMG", "ADAMH", "ADAMI", "ADAML", "ADAMM", "ADAMN", "ADAMZ", "ADBE", "ADC", "ADC^A", "ADCT", "ADEA", "ADGM", "ADI", "ADIL", "ADM", "ADMA", "ADNT", "ADP", "ADPT", "ADSE", "ADSEW", "ADSK", "ADT", "ADTN", "ADTX", "ADUR", "ADUS", "ADV", "ADVB", "ADVM", "ADX", "ADXN", "AEBI", "AEC", "AEE", "AEF", "AEFC", "AEG", "AEHL", "AEHR", "AEI", "AEIS", "AEM", "AEMD", "AENT", "AENTW", "AEO", "AEON", "AEP", "AER", "AERO", "AERT", "AERTW", "AES", "AESI", "AEVA", "AEVAW", "AEXA", "AEYE", "AFB", "AFBI", "AFCG", "AFG", "AFGB", "AFGC", "AFGD", "AFGE", "AFJK", "AFJKR", "AFJKU", "AFL", "AFRI", "AFRIW", "AFRM", "AFYA", "AG", "AGAE", "AGCC", "AGCO", "AGD", "AGEN", "AGH", "AGI", "AGIO", "AGL", "AGM", "AGM^D", "AGM^E", "AGM^F", "AGM^G", "AGM^H", "AGMH", "AGNC", "AGNCL", "AGNCM", "AGNCN", "AGNCO", "AGNCP", "AGNCZ", "AGO", "AGRO", "AGRZ", "AGX", "AGYS", "AHCO", "AHG", "AHH", "AHH^A", "AHL", "AHL^D", "AHL^E", "AHL^F", "AHMA", "AHR", "AHT", "AHT^D", "AHT^F", "AHT^G", "AHT^H", "AHT^I", "AI", "AIFF", "AIFU", "AIG", "AIHS", "AII", "AIIO", "AIIOW", "AIM", "AIMD", "AIMDW", "AIN", "AIO", "AIOT", "AIP", "AIR", "AIRE", "AIRG", "AIRI", "AIRJ", "AIRJW", "AIRO", "AIRS", "AIRT", "AIRTP", "AISP", "AISPW", "AIT", "AIV", "AIXI", "AIZ", "AIZN", "AJG", "AKA", "AKAM", "AKAN", "AKBA", "AKO/A", "AKO/B", "AKR", "AKRO", "AKTX", "AL", "ALAB", "ALAR", "ALB", "ALB^A", "ALBT", "ALC", "ALCO", "ALCY", "ALDF", "ALDFW", "ALDX", "ALE", "ALEC", "ALEX", "ALF", "ALFUW", "ALG", "ALGM", "ALGN", "ALGS", "ALGT", "ALH", "ALHC", "ALISU", "ALIT", "ALK", "ALKS", "ALKT", "ALL", "ALL^B", "ALL^H", "ALL^I", "ALL^J", "ALLE", "ALLO", "ALLR", "ALLT", "ALLY", "ALM", "ALMS", "ALMU", "ALNT", "ALNY", "ALOT", "ALPS", "ALRM", "ALRS", "ALSN", "ALT", "ALTG", "ALTG^A", "ALTI", "ALTO", "ALTS", "ALUR", "ALV", "ALVO", "ALVOW", "ALX", "ALXO", "ALZN", "AM", "AMAL", "AMAT", "AMBA", "AMBC", "AMBO", "AMBP", "AMBQ", "AMBR", "AMC", "AMCR", "AMCX", "AMD", "AME", "AMG", "AMGN", "AMH", "AMH^G", "AMH^H", "AMIX", "AMKR", "AMLX", "AMN", "AMOD", "AMODW", "AMP", "AMPG", "AMPGW", "AMPH", "AMPL", "AMPX", "AMPY", "AMR", "AMRC", "AMRK", "AMRN", "AMRX", "AMRZ", "AMS", "AMSC", "AMSF", "AMST", "AMT", "AMTB", "AMTD", "AMTM", "AMTX", "AMWD", "AMWL", "AMX", "AMZE", "AMZN", "AN", "ANAB", "ANDE", "ANEB", "ANET", "ANF", "ANG^D", "ANGH", "ANGHW", "ANGI", "ANGO", "ANGX", "ANIK", "ANIP", "ANIX", "ANL", "ANNA", "ANNAW", "ANNX", "ANPA", "ANRO", "ANSC", "ANSCW", "ANTA", "ANTX", "ANVS", "ANY", "AOD", "AOMD", "AOMN", "AOMR", "AON", "AORT", "AOS", "AOSL", "AOUT", "AP", "APA", "APACU", "APAD", "APADR", "APADU", "APAM", "APD", "APEI", "APG", "APGE", "APH", "API", "APLD", "APLE", "APLM", "APLMW", "APLS", "APLT", "APM", "APO", "APO^A", "APOG", "APOS", "APP", "APPF", "APPN", "APPS", "APRE", "APT", "APTV", "APUS", "APVO", "APWC", "APXTU", "APYX", "AQB", "AQMS", "AQN", "AQNB", "AQST", "AR", "ARAI", "ARAY", "ARBB", "ARBE", "ARBEW", "ARBK",
"ARBKL", "ARCB", "ARCC", "ARCO", "ARCT", "ARDC", "ARDT", "ARDX", "ARE", "AREB", "AREBW", "AREC", "AREN", "ARES", "ARES^B", "ARGX", "ARHS", "ARI", "ARKO", "ARKOW", "ARKR", "ARL", "ARLO", "ARLP", "ARM", "ARMK", "ARMN", "ARMP", "AROC", "AROW", "ARQ", "ARQQ", "ARQQW", "ARQT", "ARR", "ARR^C", "ARRY", "ARTL", "ARTNA", "ARTV", "ARTW", "ARVN", "ARW", "ARWR", "ARX", "AS", "ASA", "ASAN", "ASB", "ASB^E", "ASB^F", "ASBA", "ASBP", "ASBPW", "ASC", "ASG", "ASGI", "ASGN", "ASH", "ASIC", "ASIX", "ASLE", "ASM", "ASMB", "ASML", "ASND", "ASNS", "ASO", "ASPC", "ASPCR", "ASPCU", "ASPI", "ASPN", "ASPS", "ASPSW", "ASPSZ", "ASR", "ASRT", "ASRV", "ASST", "ASTC", "ASTE", "ASTH", "ASTI", "ASTL", "ASTLW", "ASTS", "ASUR", "ASX", "ASYS", "ATAI", "ATAT", "ATCH", "ATEC", "ATEN", "ATER", "ATEX", "ATGE", "ATGL", "ATH^A", "ATH^B", "ATH^D", "ATH^E", "ATHA", "ATHE", "ATHM", "ATHR", "ATHS", "ATI", "ATII", "ATIIW", "ATKR", "ATLC", "ATLCL", "ATLCP", "ATLCZ", "ATLN", "ATLO", "ATLX", "ATMC", "ATMCR", "ATMCU", "ATMCW", "ATMU", "ATMV", "ATMVR", "ATMVU", "ATNI", "ATNM", "ATO", "ATOM", "ATON", "ATOS", "ATPC", "ATR", "ATRA", "ATRC", "ATRO", "ATS", "ATUS", "ATXG", "ATXS", "ATYR", "AU", "AUB", "AUB^A", "AUBN", "AUDC", "AUGO", "AUID", "AUNA", "AUPH", "AUR", "AURA", "AURE", "AUROW", "AUST", "AUTL", "AUUD", "AUUDW", "AVA", "AVAH", "AVAL", "AVAV", "AVB", "AVBC", "AVBH", "AVBP", "AVD", "AVDL", "AVGO", "AVIR", "AVK", "AVNS", "AVNT", "AVNW", "AVO", "AVPT", "AVR", "AVT", "AVTR", "AVTX", "AVX", "AVXL", "AVY", "AWF", "AWI", "AWK", "AWP", "AWR", "AWRE", "AWX", "AX", "AXG", "AXGN", "AXIA", "AXIA^", "AXIL", "AXIN", "AXINR", "AXL", "AXON", "AXP", "AXR", "AXS", "AXS^E", "AXSM", "AXTA", "AXTI", "AYI", "AYTU", "AZ", "AZI", "AZN", "AZO", "AZTA", "AZTR", "AZZ", "B", "BA", "BA^A", "BABA", "BAC", "BAC^B", "BAC^E", "BAC^K", "BAC^L", "BAC^M", "BAC^N", "BAC^O", "BAC^P", "BAC^Q", "BAC^S", "BACC", "BACCR", "BACCU", "BACQ", "BACQR", "BAER", "BAERW", "BAFN", "BAH", "BAK", "BALL", "BALY", "BAM", "BANC", "BANC^F", "BAND", "BANF", "BANFP", "BANL", "BANR", "BANX", "BAOS", "BAP", "BARK", "BATL", "BATRA", "BATRK", "BAX", "BB", "BBAI", "BBAR", "BBBY", "BBCP", "BBD", "BBDC", "BBDO", "BBGI", "BBIO", "BBLG", "BBLGW", "BBN", "BBNX", "BBOT", "BBSI", "BBT", "BBU", "BBUC", "BBVA", "BBW", "BBWI", "BBY", "BC", "BC^A", "BC^C", "BCAB", "BCAL", "BCAR", "BCAT", "BCAX", "BCBP", "BCC", "BCDA", "BCE", "BCG", "BCH", "BCIC", "BCML", "BCO", "BCPC", "BCRX", "BCS", "BCSF", "BCTX", "BCTXW", "BCTXZ", "BCV", "BCV^A", "BCX", "BCYC", "BDC", "BDCI", "BDCIU", "BDCIW", "BDJ", "BDL", "BDMD", "BDMDW", "BDN", "BDRX", "BDSX", "BDTX", "BDX", "BE", "BEAG", "BEAGR", "BEAGU", "BEAM", "BEAT", "BEDU", "BEEM", "BEEP", "BEKE", "BELFA", "BELFB", "BEN", "BENF", "BENFW", "BEP", "BEP^A", "BEPC", "BEPH", "BEPI", "BEPJ", "BETA", "BETR", "BETRW", "BF/A", "BF/B", "BFAM", "BFC", "BFH", "BFIN", "BFK", "BFLY", "BFRG", "BFRGW", "BFRI", "BFS", "BFS^D", "BFS^E", "BFST", "BFZ", "BG", "BGB", "BGC", "BGH", "BGI", "BGIN", "BGL", "BGLC", "BGLWW", "BGM", "BGMS", "BGMSP", "BGR", "BGS", "BGSF", "BGSI", "BGT", "BGX", "BGY", "BH", "BHAT", "BHB", "BHC", "BHE", "BHF", "BHFAL", "BHFAM", "BHFAN", "BHFAO", "BHFAP", "BHK", "BHM", "BHP", "BHR", "BHR^B", "BHR^D", "BHRB", "BHST", "BHV", "BHVN", "BIAF", "BIAFW", "BIDU", "BIIB", "BILI", "BILL", "BIO", "BIO/B", "BIOA", "BIOX", "BIP", "BIP^A", "BIP^B", "BIPC", "BIPH", "BIPI", "BIPJ", "BIRD", "BIRK", "BIT", "BITF", "BIVI", "BIYA", "BJ", "BJDX", "BJRI", "BK", "BK^K", "BKD", "BKE", "BKH", "BKHA", "BKHAR", "BKKT", "BKN", "BKNG", "BKR", "BKSY", "BKT", "BKTI", "BKU", "BKV", "BKYI", "BL", "BLBD", "BLBX", "BLCO", "BLD", "BLDP", "BLDR", "BLE", "BLFS", "BLFY", "BLIN",
"BLIV", "BLK", "BLKB", "BLLN", "BLMN", "BLMZ", "BLND", "BLNE", "BLNK", "BLRX", "BLSH", "BLTE", "BLUW", "BLUWU", "BLUWW", "BLW", "BLX", "BLZE", "BLZR", "BLZRU", "BLZRW", "BMA", "BMBL", "BME", "BMEA", "BMEZ", "BMGL", "BMHL", "BMI", "BML^G", "BML^H", "BML^J", "BML^L", "BMN", "BMNR", "BMO", "BMR", "BMRA", "BMRC", "BMRN", "BMY", "BN", "BNAI", "BNAIW", "BNBX", "BNC", "BNCWW", "BNED", "BNGO", "BNH", "BNJ", "BNKK", "BNL", "BNR", "BNRG", "BNS", "BNT", "BNTC", "BNTX", "BNY", "BNZI", "BNZIW", "BOC", "BODI", "BOE", "BOF", "BOH", "BOH^A", "BOH^B", "BOKF", "BOLD", "BOLT", "BON", "BOOM", "BOOT", "BORR", "BOSC", "BOTJ", "BOW", "BOX", "BOXL", "BP", "BPACU", "BPOP", "BPOPM", "BPRN", "BPYPM", "BPYPN", "BPYPO", "BPYPP", "BQ", "BR", "BRAG", "BRBI", "BRBR", "BRBS", "BRC", "BRCB", "BRCC", "BRFH", "BRIA", "BRID", "BRK/A", "BRK/B", "BRKR", "BRKRP", "BRLS", "BRLSW", "BRLT", "BRN", "BRNS", "BRO", "BROS", "BRR", "BRRWW", "BRSL", "BRSP", "BRT", "BRTX", "BRW", "BRX", "BRY", "BRZE", "BSAA", "BSAAU", "BSAC", "BSBK", "BSBR", "BSET", "BSL", "BSLK", "BSLKW", "BSM", "BSRR", "BST", "BSTZ", "BSVN", "BSX", "BSY", "BTA", "BTAI", "BTBD", "BTBDW", "BTBT", "BTCS", "BTCT", "BTDR", "BTE", "BTG", "BTI", "BTM", "BTMD", "BTMWW", "BTO", "BTOC", "BTOG", "BTQ", "BTSG", "BTSGU", "BTT", "BTTC", "BTU", "BTX", "BTZ", "BUD", "BUI", "BULL", "BULLW", "BUR", "BURL", "BURU", "BUSE", "BUSEP", "BUUU", "BV", "BVFL", "BVN", "BVS", "BW", "BW^A", "BWA", "BWAY", "BWB", "BWBBP", "BWEN", "BWFG", "BWG", "BWIN", "BWLP", "BWMN", "BWMX", "BWNB", "BWSN", "BWXT", "BX", "BXC", "BXMT", "BXMX", "BXP", "BXSL", "BY", "BYAH", "BYD", "BYFC", "BYM", "BYND", "BYRN", "BYSI", "BZ", "BZAI", "BZAIW", "BZFD", "BZFDW", "BZH", "BZUN", "C", "C^N", "CAAP", "CAAS", "CABA", "CABO", "CABR", "CAC", "CACC", "CACI", "CADE", "CADE^A", "CADL", "CAE", "CAEP", "CAF", "CAG", "CAH", "CAI", "CAKE", "CAL", "CALC", "CALM", "CALX", "CAMP", "CAMT", "CAN", "CANF", "CANG", "CAPL", "CAPN", "CAPNU", "CAPR", "CAPS", "CAPT", "CAPTW", "CAR", "CARE", "CARG", "CARL", "CARR", "CARS", "CART", "CARV", "CASH", "CASI", "CASS", "CASY", "CAT", "CATO", "CATX", "CATY", "CAVA", "CB", "CBAN", "CBAT", "CBFV", "CBIO", "CBK", "CBL", "CBLL", "CBNA", "CBNK", "CBOE", "CBRE", "CBRL", "CBSH", "CBT", "CBU", "CBUS", "CBZ", "CC", "CCAP", "CCB", "CCBG", "CCC", "CCCC", "CCCX", "CCCXU", "CCCXW", "CCD", "CCEC", "CCEL", "CCEP", "CCG", "CCHH", "CCI", "CCID", "CCIF", "CCII", "CCIIU", "CCIIW", "CCIX", "CCIXW", "CCJ", "CCK", "CCL", "CCLD", "CCLDO", "CCM", "CCNE", "CCNEP", "CCO", "CCOI", "CCRN", "CCS", "CCSI", "CCTG", "CCU", "CCZ", "CD", "CDE", "CDIO", "CDLR", "CDLX", "CDNA", "CDNS", "CDP", "CDR^B", "CDR^C", "CDRE", "CDRO", "CDROW", "CDT", "CDTG", "CDTTW", "CDTX", "CDW", "CDXS", "CDZI", "CDZIP", "CE", "CECO", "CEE", "CEG", "CELC", "CELH", "CELU", "CELUW", "CELZ", "CENN", "CENT", "CENTA", "CENX", "CEP", "CEPF", "CEPO", "CEPT", "CEPU", "CEPV", "CERS", "CERT", "CET", "CETX", "CETY", "CEV", "CEVA", "CF", "CFBK", "CFFI", "CFFN", "CFG", "CFG^E", "CFG^H", "CFG^I", "CFLT", "CFND", "CFR", "CFR^B", "CG", "CGABL", "CGAU", "CGBD", "CGBDL", "CGC", "CGCT", "CGCTW", "CGEM", "CGEN", "CGNT", "CGNX", "CGO", "CGON", "CGTL", "CGTX", "CHA", "CHAC", "CHACR", "CHACU", "CHAR", "CHARR", "CHCI", "CHCO", "CHCT", "CHD", "CHDN", "CHE", "CHEC", "CHECU", "CHECW", "CHEF", "CHEK", "CHGG", "CHH", "CHI", "CHKP", "CHMG", "CHMI", "CHMI^A", "CHMI^B", "CHNR", "CHOW", "CHPG", "CHPGR", "CHPGU", "CHPT", "CHR", "CHRD", "CHRS", "CHRW", "CHSCL", "CHSCM", "CHSCN", "CHSCO", "CHSCP", "CHSN", "CHT", "CHTR", "CHW", "CHWY", "CHY", "CHYM", "CI", "CIA", "CIB", "CICB", "CIEN", "CIF", "CIFR", "CIFRW", "CIG", "CIGI", "CIGL", "CII", "CIIT", "CIK", "CIM",
"CIM^A", "CIM^B", "CIM^C", "CIM^D", "CIMN", "CIMO", "CIMP", "CINF", "CING", "CINGW", "CINT", "CIO", "CIO^A", "CION", "CISO", "CISS", "CIVB", "CIVI", "CIX", "CJET", "CJMB", "CKX", "CL", "CLAR", "CLB", "CLBK", "CLBT", "CLCO", "CLDI", "CLDT", "CLDT^A", "CLDX", "CLF", "CLFD", "CLGN", "CLH", "CLIK", "CLIR", "CLLS", "CLM", "CLMB", "CLMT", "CLNE", "CLNN", "CLNNW", "CLOV", "CLPR", "CLPS", "CLPT", "CLRB", "CLRO", "CLS", "CLSD", "CLSK", "CLSKW", "CLST", "CLVT", "CLW", "CLWT", "CLX", "CLYM", "CM", "CMA", "CMA^B", "CMBM", "CMBT", "CMC", "CMCL", "CMCM", "CMCO", "CMCSA", "CMCT", "CMDB", "CME", "CMG", "CMI", "CMMB", "CMND", "CMP", "CMPO", "CMPOW", "CMPR", "CMPS", "CMPX", "CMRC", "CMRE", "CMRE^B", "CMRE^C", "CMRE^D", "CMS", "CMS^B", "CMS^C", "CMSA", "CMSC", "CMSD", "CMT", "CMTG", "CMTL", "CMU", "CNA", "CNC", "CNCK", "CNCKW", "CNDT", "CNET", "CNEY", "CNF", "CNH", "CNI", "CNK", "CNL", "CNM", "CNMD", "CNNE", "CNO", "CNO^A", "CNOB", "CNOBP", "CNP", "CNQ", "CNR", "CNS", "CNSP", "CNTA", "CNTB", "CNTX", "CNTY", "CNVS", "CNX", "CNXC", "CNXN", "COCH", "COCHW", "COCO", "COCP", "CODA", "CODI", "CODI^A", "CODI^B", "CODI^C", "CODX", "COE", "COEP", "COEPW", "COF", "COF^I", "COF^J", "COF^K", "COF^L", "COF^N", "COFS", "COGT", "COHN", "COHR", "COHU", "COIN", "COKE", "COLA", "COLAR", "COLAU", "COLB", "COLD", "COLL", "COLM", "COMM", "COMP", "CON", "COO", "COOK", "COOT", "COOTW", "COP", "COPL", "COR", "CORT", "CORZ", "CORZW", "CORZZ", "COSM", "COSO", "COST", "COTY", "COUR", "COYA", "CP", "CPA", "CPAC", "CPAY", "CPB", "CPBI", "CPF", "CPHC", "CPHI", "CPIX", "CPK", "CPNG", "CPOP", "CPRI", "CPRT", "CPRX", "CPS", "CPSH", "CPSS", "CPT", "CPZ", "CQP", "CR", "CRACU", "CRAI", "CRAQ", "CRAQR", "CRBD", "CRBG", "CRBP", "CRBU", "CRC", "CRCL", "CRCT", "CRD/A", "CRD/B", "CRDF", "CRDL", "CRDO", "CRE", "CREG", "CRESW", "CRESY", "CREV", "CREVW", "CREX", "CRF", "CRGO", "CRGOW", "CRGY", "CRH", "CRI", "CRIS", "CRK", "CRL", "CRM", "CRMD", "CRML", "CRMLW", "CRMT", "CRNC", "CRNT", "CRNX", "CRON", "CROX", "CRS", "CRSP", "CRSR", "CRT", "CRTO", "CRUS", "CRVL", "CRVO", "CRVS", "CRWD", "CRWS", "CRWV", "CSAI", "CSAN", "CSBR", "CSCO", "CSGP", "CSGS", "CSIQ", "CSL", "CSPI", "CSQ", "CSR", "CSTE", "CSTL", "CSTM", "CSV", "CSW", "CSWC", "CSX", "CTA^A", "CTA^B", "CTAS", "CTBB", "CTBI", "CTDD", "CTEV", "CTGO", "CTKB", "CTLP", "CTM", "CTMX", "CTNM", "CTNT", "CTO", "CTO^A", "CTOR", "CTOS", "CTRA", "CTRE", "CTRI", "CTRM", "CTRN", "CTS", "CTSH", "CTSO", "CTVA", "CTW", "CTXR", "CUB", "CUBB", "CUBE", "CUBI", "CUBI^F", "CUBWU", "CUBWW", "CUE", "CUK", "CULP", "CUPR", "CURB", "CURI", "CURR", "CURV", "CURX", "CUZ", "CV", "CVAC", "CVBF", "CVCO", "CVE", "CVEO", "CVGI", "CVGW", "CVI", "CVKD", "CVLG", "CVLT", "CVM", "CVNA", "CVR", "CVRX", "CVS", "CVU", "CVV", "CVX", "CW", "CWAN", "CWBC", "CWCO", "CWD", "CWEN", "CWH", "CWK", "CWST", "CWT", "CX", "CXAI", "CXAIW", "CXDO", "CXE", "CXH", "CXM", "CXT", "CXW", "CYBN", "CYBR", "CYCN", "CYCU", "CYCUW", "CYD", "CYH", "CYN", "CYPH", "CYRX", "CYTK", "CZFS", "CZNC", "CZR", "CZWI", "D", "DAAQ", "DAAQU", "DAAQW", "DAC", "DAIC", "DAICW", "DAIO", "DAKT", "DAL", "DAN", "DAO", "DAR", "DARE", "DASH", "DAVA", "DAVE", "DAVEW", "DAWN", "DAY", "DB", "DBD", "DBGI", "DBI", "DBL", "DBRG", "DBRG^H", "DBRG^I", "DBRG^J", "DBVT", "DBX", "DC", "DCBO", "DCGO", "DCI", "DCO", "DCOM", "DCOMG", "DCOMP", "DCTH", "DD", "DDC", "DDD", "DDI", "DDL", "DDOG", "DDS", "DDT", "DE", "DEA", "DEC", "DECK", "DEFT", "DEI", "DELL", "DENN", "DEO", "DERM", "DEVS", "DFDV", "DFDVW", "DFH", "DFIN", "DFLI", "DFLIW", "DFP", "DFSC", "DFSCW", "DG", "DGICA", "DGICB", "DGII", "DGLY", "DGNX", "DGX", "DGXX", "DH", "DHC", "DHCNI", "DHCNL", "DHF", "DHI",
"DHIL", "DHR", "DHT", "DHX", "DHY", "DIAX", "DIBS", "DIN", "DINO", "DIOD", "DIS", "DIT", "DJCO", "DJT", "DJTWW", "DK", "DKI", "DKL", "DKNG", "DKS", "DLB", "DLHC", "DLNG", "DLNG^A", "DLO", "DLPN", "DLR", "DLR^J", "DLR^K", "DLR^L", "DLTH", "DLTR", "DLX", "DLXY", "DLY", "DMA", "DMAA", "DMAAR", "DMAAU", "DMAC", "DMB", "DMIIU", "DMLP", "DMO", "DMRC", "DNA", "DNLI", "DNMXU", "DNN", "DNOW", "DNP", "DNTH", "DNUT", "DOC", "DOCN", "DOCS", "DOCU", "DOGZ", "DOLE", "DOMH", "DOMO", "DOOO", "DORM", "DOUG", "DOV", "DOW", "DOX", "DOYU", "DPG", "DPRO", "DPZ", "DQ", "DRCT", "DRD", "DRDB", "DRDBW", "DRH", "DRH^A", "DRI", "DRIO", "DRMA", "DRS", "DRTS", "DRTSW", "DRUG", "DRVN", "DSGN", "DSGR", "DSGX", "DSL", "DSM", "DSP", "DSS", "DSU", "DSWL", "DSX", "DSX^B", "DSY", "DSYWW", "DT", "DTB", "DTCK", "DTE", "DTF", "DTG", "DTI", "DTIL", "DTK", "DTM", "DTSQ", "DTSQR", "DTSQU", "DTSS", "DTST", "DTSTW", "DTW", "DUK", "DUK^A", "DUKB", "DUO", "DUOL", "DUOT", "DV", "DVA", "DVAX", "DVLT", "DVN", "DVS", "DWSN", "DWTX", "DX", "DX^C", "DXC", "DXCM", "DXF", "DXLG", "DXPE", "DXR", "DXST", "DXYZ", "DY", "DYAI", "DYCQ", "DYCQR", "DYN", "DYORU", "E", "EA", "EAD", "EAF", "EAI", "EARN", "EAT", "EB", "EBAY", "EBC", "EBF", "EBMT", "EBON", "EBS", "EC", "ECAT", "ECBK", "ECC           ", "ECC^D", "ECCC", "ECCF", "ECCU", "ECCV", "ECCW", "ECCX", "ECDA", "ECDAW", "ECF", "ECF^A", "ECG", "ECL", "ECO", "ECOR", "ECPG", "ECVT", "ECX", "ECXWW", "ED", "EDAP", "EDBL", "EDBLW", "EDD", "EDF", "EDHL", "EDIT", "EDN", "EDRY", "EDSA", "EDTK", "EDU", "EDUC", "EE", "EEA", "EEFT", "EEIQ", "EEX", "EFC", "EFC^A", "EFC^B", "EFC^C", "EFC^D", "EFOI", "EFR", "EFSC", "EFSCP", "EFSI", "EFT", "EFX", "EFXT", "EG", "EGAN", "EGBN", "EGG", "EGHA", "EGHAR", "EGHT", "EGY", "EH", "EHAB", "EHC", "EHGO", "EHI", "EHLD", "EHTH", "EIC", "EICA", "EICB", "EICC", "EIG", "EIIA", "EIM", "EIX", "EJH", "EKSO", "EL", "ELA", "ELAB", "ELAN", "ELBM", "ELC", "ELDN", "ELF", "ELLO", "ELMD", "ELME", "ELOG", "ELP", "ELPC", "ELPW", "ELS", "ELSE", "ELTK", "ELTX", "ELUT", "ELV", "ELVA", "ELVN", "ELVR", "ELWS", "ELWT", "EM", "EMA", "EMBC", "EMBJ", "EMD", "EME", "EMF", "EMIS", "EMISR", "EML", "EMN", "EMO", "EMP", "EMPD", "EMR", "ENB", "ENGN", "ENGNW", "ENGS", "ENIC", "ENJ", "ENLT", "ENLV", "ENO", "ENOV", "ENPH", "ENR", "ENS", "ENSC", "ENSG", "ENTA", "ENTG", "ENTO", "ENTX", "ENVA", "ENVB", "ENVX", "EOD", "EOG", "EOI", "EOLS", "EONR", "EOS", "EOSE", "EOSEW", "EOT", "EP", "EP^C", "EPAC", "EPAM", "EPC", "EPD", "EPM", "EPOW", "EPR", "EPR^C", "EPR^E", "EPR^G", "EPRT", "EPRX", "EPSM", "EPSN", "EPWK", "EQ", "EQBK", "EQH", "EQH^A", "EQH^C", "EQIX", "EQNR", "EQR", "EQS", "EQT", "EQX", "ERAS", "ERC", "ERH", "ERIC", "ERIE", "ERII", "ERNA", "ERO", "ES", "ESAB", "ESCA", "ESE", "ESEA", "ESGL", "ESHAR", "ESI", "ESLA", "ESLAW", "ESLT", "ESNT", "ESOA", "ESP", "ESPR", "ESQ", "ESRT", "ESS", "ESTA", "ESTC", "ET", "ET^I", "ETB", "ETD", "ETG", "ETHM", "ETHMU", "ETHMW", "ETHZ", "ETI^", "ETJ", "ETN", "ETO", "ETON", "ETOR", "ETR", "ETS", "ETSY", "ETV", "ETW", "ETX           ", "ETY", "EU", "EUDA", "EUDAW", "EURK", "EURKR", "EVAC", "EVAX", "EVC", "EVCM", "EVER", "EVEX", "EVF", "EVG", "EVGN", "EVGO", "EVGOW", "EVH", "EVI", "EVLV", "EVLVW", "EVMN", "EVN", "EVO", "EVOK", "EVOXU", "EVR", "EVRG", "EVT", "EVTC", "EVTL", "EVTV", "EVV", "EW", "EWBC", "EWCZ", "EWTX", "EXAS", "EXC", "EXE", "EXEEL", "EXEL", "EXFY", "EXG", "EXK", "EXLS", "EXOD", "EXOZ", "EXP", "EXPD", "EXPE", "EXPI", "EXPO", "EXR", "EXTR", "EYE", "EYPT", "EZGO", "EZPW", "F", "F^B", "F^C", "F^D", "FA", "FACT", "FACTW", "FAF", "FAMI", "FANG", "FARM", "FAST", "FAT", "FATBB", "FATBP", "FATE", "FATN", "FAX", "FBGL", "FBIN", "FBIO", "FBIOP",
"FBIZ", "FBK", "FBLA", "FBLG", "FBNC", "FBP", "FBRT", "FBRT^E", "FBRX", "FBYD", "FBYDW", "FC", "FCAP", "FCBC", "FCCO", "FCEL", "FCF", "FCFS", "FCHL", "FCN", "FCNCA", "FCNCO", "FCNCP", "FCO", "FCPT", "FCRX", "FCT", "FCUV", "FCX", "FDBC", "FDMT", "FDP", "FDS", "FDSB", "FDUS", "FDX", "FE", "FEAM", "FEBO", "FEDU", "FEIM", "FELE", "FEMY", "FENC", "FENG", "FER", "FERA", "FERAR", "FERG", "FET", "FF", "FFA", "FFAI", "FFAIW", "FFBC", "FFC", "FFIC", "FFIN", "FFIV", "FFWM", "FG", "FGBI", "FGBIP", "FGEN", "FGI", "FGIWW", "FGL", "FGMC", "FGMCR", "FGMCU", "FGN", "FGNX", "FGNXP", "FGSN", "FHB", "FHI", "FHN", "FHN^C", "FHN^E", "FHN^F", "FHTX", "FIBK", "FICO", "FIEE", "FIG", "FIGR", "FIGS", "FIGX", "FIGXU", "FIGXW", "FIHL", "FINS", "FINV", "FINW", "FIP", "FIS", "FISI", "FISV", "FITB", "FITBI", "FITBO", "FITBP", "FIVE", "FIVN", "FIX", "FIZZ", "FKWL", "FLC", "FLD", "FLDDW", "FLEX", "FLG", "FLG^A", "FLG^U", "FLGC", "FLGT", "FLL", "FLNC", "FLNG", "FLNT", "FLO", "FLOC", "FLR", "FLS", "FLUT", "FLUX", "FLWS", "FLX", "FLXS", "FLY", "FLYE", "FLYW", "FLYX", "FMAO", "FMBH", "FMC", "FMFC", "FMN", "FMNB", "FMS", "FMST", "FMSTW", "FMX", "FMY", "FN", "FNB", "FND", "FNF", "FNGR", "FNKO", "FNLC", "FNV", "FNWB", "FNWD", "FOA", "FOF", "FOFO", "FOLD", "FONR", "FOR", "FORA", "FORD", "FORM", "FORR", "FORTY", "FOSL", "FOSLL", "FOUR", "FOUR^A", "FOX", "FOXA", "FOXF", "FOXX", "FOXXW", "FPF", "FPH", "FPI", "FR", "FRA", "FRAF", "FRBA", "FRD", "FRGE", "FRGT", "FRHC", "FRME", "FRMEP", "FRMI", "FRO", "FROG", "FRPH", "FRPT", "FRSH", "FRST", "FRSX", "FRT", "FRT^C", "FSBC", "FSBW", "FSCO", "FSEA", "FSFG", "FSHP", "FSHPR", "FSI", "FSK", "FSLR", "FSLY", "FSM", "FSP", "FSS", "FSSL", "FSTR", "FSUN", "FSV", "FT", "FTAI", "FTAIM", "FTAIN", "FTCI", "FTDR", "FTEK", "FTEL", "FTF", "FTFT", "FTHM", "FTHY", "FTI", "FTK", "FTLF", "FTNT", "FTRE", "FTRK", "FTS", "FTV", "FTW", "FUBO", "FUFU", "FUFUW", "FUL", "FULC", "FULT", "FULTP", "FUN", "FUNC", "FUND", "FURY", "FUSB", "FUSE", "FUSEW", "FUTU", "FVCB", "FVN", "FVNNR", "FVR", "FVRR", "FWONA", "FWONK", "FWRD", "FWRG", "FXNC", "FYBR", "G", "GAB", "GAB^G", "GAB^H", "GAB^K", "GABC", "GAIA", "GAIN", "GAINI", "GAINL", "GAINN", "GAINZ", "GALT", "GAM", "GAM^B", "GAMB", "GAME", "GANX", "GAP", "GASS", "GATX", "GAU", "GAUZ", "GBAB", "GBCI", "GBDC", "GBFH", "GBIO", "GBLI", "GBR", "GBTG", "GBX", "GCBC", "GCI", "GCL", "GCMG", "GCMGW", "GCO", "GCT", "GCTK", "GCTS", "GCV", "GD", "GDC", "GDDY", "GDEN", "GDEV", "GDEVW", "GDHG", "GDL", "GDO", "GDOT", "GDRX", "GDS", "GDTC", "GDV", "GDV^H", "GDV^K", "GDYN", "GE", "GECC", "GECCG", "GECCH", "GECCI", "GECCO", "GEF", "GEG", "GEGGL", "GEHC", "GEL", "GELS", "GEMI", "GEN", "GENC", "GENI", "GENK", "GENVR", "GEO", "GEOS", "GERN", "GES", "GETY", "GEV", "GEVO", "GF", "GFAI", "GFAIW", "GFF", "GFI", "GFL", "GFR", "GFS", "GGAL", "GGB", "GGG", "GGN", "GGN^B", "GGR", "GGROW", "GGT", "GGT^E", "GGT^G", "GGZ", "GH", "GHC", "GHG", "GHI", "GHLD", "GHM", "GHRS", "GHY", "GIB", "GIBO", "GIC", "GIFI", "GIFT", "GIG", "GIGGU", "GIGGW", "GIGM", "GIII", "GIL", "GILD", "GILT", "GIPR", "GIPRW", "GIS", "GITS", "GIW", "GIWWR", "GIWWU", "GJH", "GJO", "GJS", "GJT", "GKOS", "GL", "GL^D", "GLAD", "GLBE", "GLBS", "GLBZ", "GLDD", "GLDG", "GLE", "GLIBA", "GLIBK", "GLMD", "GLNG", "GLO", "GLOB", "GLOP^A", "GLOP^B", "GLOP^C", "GLP", "GLP^B", "GLPG", "GLPI", "GLQ", "GLRE", "GLSI", "GLTO", "GLU", "GLU^B", "GLUE", "GLV", "GLW", "GLXG", "GLXY", "GM", "GMAB", "GME", "GMED", "GMGI", "GMHS", "GMM", "GMRE", "GMRE^A", "GNE", "GNFT", "GNK", "GNL", "GNL^A", "GNL^B", "GNL^D", "GNL^E", "GNLN", "GNLX", "GNPX", "GNRC", "GNS", "GNSS", "GNT", "GNT^A", "GNTA", "GNTX", "GNW", "GO", "GOCO", "GOF", "GOGO",
"GOLF", "GOOD", "GOODN", "GOODO", "GOOG", "GOOGL", "GOOS", "GORO", "GORV", "GOSS", "GOTU", "GOVX", "GP", "GPAT", "GPATW", "GPC", "GPCR", "GPI", "GPJA", "GPK", "GPMT", "GPMT^A", "GPN", "GPOR", "GPRE", "GPRK", "GPRO", "GPUS", "GPUS^D", "GRAB", "GRABW", "GRAF", "GRAL", "GRAN", "GRBK", "GRBK^A", "GRC", "GRCE", "GRDN", "GREE", "GREEL", "GRF", "GRFS", "GRI", "GRMN", "GRND", "GRNQ", "GRNT", "GRO", "GROV", "GROW", "GROY", "GRPN", "GRRR", "GRRRW", "GRVY", "GRWG", "GRX", "GS", "GS^A", "GS^C", "GS^D", "GSAT", "GSBC", "GSBD", "GSHD", "GSHR", "GSHRW", "GSIT", "GSIW", "GSK", "GSL", "GSL^B", "GSM", "GSRF", "GSRFR", "GSRFU", "GSUN", "GT", "GTBP", "GTE", "GTEC", "GTEN", "GTENW", "GTERA", "GTERR", "GTERU", "GTERW", "GTES", "GTIM", "GTLB", "GTLS", "GTLS^B", "GTM", "GTN", "GTX", "GTY", "GUG", "GUT", "GUT^C", "GUTS", "GV", "GVA", "GVH", "GWAV", "GWH", "GWRE", "GWRS", "GWW", "GXAI", "GXO", "GYRE", "GYRO", "H", "HAE", "HAFC", "HAFN", "HAIN", "HAL", "HALO", "HAO", "HAS", "HASI", "HAVAU", "HAYW", "HBAN", "HBANL", "HBANM", "HBANP", "HBB", "HBCP", "HBI", "HBIO", "HBM", "HBNB", "HBNC", "HBR", "HBT", "HCA", "HCAI", "HCAT", "HCC", "HCHL", "HCI", "HCKT", "HCM", "HCMA", "HCMAU", "HCMAW", "HCSG", "HCTI", "HCWB", "HCWC", "HCXY", "HD", "HDB", "HDL", "HDSN", "HE", "HEI", "HEI/A", "HELE", "HEPS", "HEQ", "HERE", "HERZ", "HESM", "HFBL", "HFFG", "HFRO", "HFRO^A", "HFRO^B", "HFWA", "HG", "HGBL", "HGLB", "HGTY", "HGV", "HHH", "HHS", "HI", "HIFS", "HIG", "HIG^G", "HIHO", "HII", "HIMS", "HIMX", "HIND", "HIO", "HIPO", "HIT", "HITI", "HIVE", "HIW", "HIX", "HKD", "HKIT", "HKPD", "HL", "HL^B", "HLF", "HLI", "HLIO", "HLIT", "HLLY", "HLMN", "HLN", "HLNE", "HLP", "HLT", "HLX", "HMC", "HMN", "HMR", "HMY", "HNGE", "HNI", "HNNA", "HNNAZ", "HNRG", "HNST", "HNVR", "HOFT", "HOG", "HOLO", "HOLOW", "HOLX", "HOMB", "HON", "HOOD", "HOPE", "HOTH", "HOUR", "HOUS", "HOV", "HOVNP", "HOVR", "HOVRW", "HOWL", "HP", "HPAI", "HPAIW", "HPE", "HPE^C", "HPF", "HPI", "HPK", "HPP", "HPP^C", "HPQ", "HPS", "HQH", "HQI", "HQL", "HQY", "HR", "HRB", "HRI", "HRL", "HRMY", "HROW", "HRTG", "HRTX", "HRZN", "HSAI", "HSBC", "HSCS", "HSCSW", "HSDT", "HSHP", "HSIC", "HSII", "HSPO", "HSPOU", "HSPOW", "HSPT", "HSPTU", "HST", "HSTM", "HSY", "HTB", "HTBK", "HTCO", "HTCR", "HTD", "HTFB", "HTFC", "HTFL", "HTGC", "HTH", "HTHT", "HTLD", "HTLM", "HTO", "HTOO", "HTOOW", "HTZ", "HTZWW", "HUBB", "HUBC", "HUBCW", "HUBCZ", "HUBG", "HUBS", "HUDI", "HUHU", "HUIZ", "HUM", "HUMA", "HUMAW", "HUN", "HURA", "HURC", "HURN", "HUSA", "HUT", "HUYA", "HVII", "HVIIR", "HVIIU", "HVMC", "HVMCW", "HVT", "HVT/A", "HWBK", "HWC", "HWCPZ", "HWH", "HWKN", "HWM", "HWM^", "HXHX", "HXL", "HY", "HYAC", "HYFM", "HYFT", "HYI", "HYLN", "HYMC", "HYPD", "HYPR", "HYT", "HZO", "IAC", "IAE", "IAF", "IAG", "IART", "IAS", "IAUX", "IBAC", "IBCP", "IBEX", "IBG", "IBIO", "IBKR", "IBM", "IBN", "IBO", "IBOC", "IBP", "IBRX", "IBTA", "ICCC", "ICCM", "ICE", "ICFI", "ICG", "ICHR", "ICL", "ICLR", "ICMB", "ICON", "ICR^A", "ICU", "ICUCW", "ICUI", "IDA", "IDAI", "IDCC", "IDE", "IDN", "IDR", "IDT", "IDXX", "IDYA", "IE", "IEP", "IESC", "IEX", "IFBD", "IFF", "IFN", "IFRX", "IFS", "IGA", "IGC", "IGD", "IGI", "IGIC", "IGR", "IH", "IHD", "IHG", "IHRT", "IHS", "IHT", "IIF", "III", "IIIN", "IIIV", "IIM", "IINN", "IINNW", "IIPR", "IIPR^A", "IKT", "ILAG", "ILLR", "ILLRW", "ILMN", "ILPT", "IMA", "IMAX", "IMCC", "IMCR", "IMDX", "IMG", "IMKTA", "IMMP", "IMMR", "IMMX", "IMNM", "IMNN", "IMO", "IMOS", "IMPP", "IMPPP", "IMRN", "IMRX", "IMSR", "IMSRW", "IMTE", "IMTX", "IMUX", "IMVT", "IMXI", "INAB", "INAC", "INACR", "INACU", "INBK", "INBKZ", "INBS", "INBX", "INCR", "INCY", "INDB", "INDI", "INDO", "INDP", "INDV", "INEO", 
"INFA", "INFU", "INFY", "ING", "INGM", "INGN", "INGR", "INHD", "INKT", "INLF", "INLX", "INM", "INMB", "INMD", "INN", "INN^E", "INN^F", "INNV", "INO", "INOD", "INR", "INSE", "INSG", "INSM", "INSP", "INSW", "INTA", "INTC", "INTG", "INTJ", "INTR", "INTS", "INTT", "INTU", "INTZ", "INUV", "INV", "INVA", "INVE", "INVH", "INVX", "INVZ", "INVZW", "IOBT", "IONQ", "IONR", "IONS", "IOR", "IOSP", "IOT", "IOTR", "IOVA", "IP", "IPAR", "IPCX", "IPCXR", "IPCXU", "IPDN", "IPG", "IPGP", "IPHA", "IPI", "IPM", "IPOD", "IPODW", "IPSC", "IPST", "IPW", "IPWR", "IPX", "IQ", "IQI", "IQST", "IQV", "IR", "IRBT", "IRD", "IRDM", "IREN", "IRIX", "IRM", "IRMD", "IRON", "IROQ", "IRS", "IRT", "IRTC", "IRWD", "ISBA", "ISD", "ISOU", "ISPC", "ISPO", "ISPOW", "ISPR", "ISRG", "ISRL", "ISRLW", "ISSC", "ISTR", "IT", "ITGR", "ITIC", "ITP", "ITRG", "ITRI", "ITRM", "ITRN", "ITT", "ITUB", "ITW", "IVA", "IVDA", "IVDAW", "IVF", "IVP", "IVR", "IVR^C", "IVT", "IVVD", "IVZ", "IX", "IXHL", "IZEA", "IZM", "J", "JACK", "JACS", "JAGX", "JAKK", "JAMF", "JANX", "JAZZ", "JBDI", "JBGS", "JBHT", "JBI", "JBIO", "JBK", "JBL", "JBLU", "JBS", "JBSS", "JBTM", "JCAP", "JCE", "JCI", "JCSE", "JCTC", "JD", "JDZG", "JEF", "JELD", "JEM", "JENA", "JFB", "JFBR", "JFBRW", "JFIN", "JFR", "JFU", "JG", "JGH", "JHG", "JHI", "JHS", "JHX", "JILL", "JJSF", "JKHY", "JKS", "JL", "JLHL", "JLL", "JLS", "JMIA", "JMM", "JMSB", "JNJ", "JOB", "JOBY", "JOE", "JOF", "JOUT", "JOYY", "JPC", "JPM", "JPM^C", "JPM^D", "JPM^J", "JPM^K", "JPM^L", "JPM^M", "JQC", "JRI", "JRS", "JRSH", "JRVR", "JSM", "JSPR", "JSPRW", "JTAI", "JUNS", "JVA", "JWEL", "JXG", "JXN", "JXN^A", "JYD", "JYNT", "JZ", "JZXN", "K", "KAI", "KALA", "KALU", "KALV", "KAPA", "KAR", "KARO", "KAVL", "KB", "KBDC", "KBH", "KBR", "KBSX", "KC", "KCHV", "KCHVR", "KCHVU", "KD", "KDK", "KDKRW", "KDP", "KE", "KELYA", "KELYB", "KEN", "KEP", "KEQU", "KEX", "KEY", "KEY^I", "KEY^J", "KEY^K", "KEY^L", "KEYS", "KF", "KFFB", "KFII", "KFIIR", "KFRC", "KFS", "KFY", "KG", "KGC", "KGEI", "KGS", "KHC", "KIDS", "KIDZ", "KIDZW", "KIM", "KIM^L", "KIM^M", "KIM^N", "KINS", "KIO", "KITT", "KITTW", "KKR", "KKR^D", "KKRS", "KKRT", "KLAC", "KLAR", "KLC", "KLIC", "KLRS", "KLTO", "KLTOW", "KLTR", "KLXE", "KMB", "KMDA", "KMI", "KMPB", "KMPR", "KMRK", "KMT", "KMTS", "KMX", "KN", "KNDI", "KNF", "KNOP", "KNRX", "KNSA", "KNSL", "KNTK", "KNX", "KO", "KOD", "KODK", "KOF", "KOP", "KOPN", "KORE", "KOS", "KOSS", "KOYN", "KOYNU", "KOYNW", "KPLT", "KPLTW", "KPRX", "KPTI", "KR", "KRC", "KREF", "KREF^A", "KRG", "KRKR", "KRMD", "KRMN", "KRNT", "KRNY", "KRO", "KROS", "KRP", "KRRO", "KRT", "KRUS", "KRYS", "KSCP", "KSPI", "KSS", "KT", "KTB", "KTCC", "KTF", "KTH", "KTN", "KTOS", "KTTA", "KTTAW", "KULR", "KURA", "KVAC", "KVACW", "KVHI", "KVUE", "KVYO", "KW", "KWM", "KWMWW", "KWR", "KXIN", "KYIV", "KYIVW", "KYMR", "KYN", "KYTX", "KZIA", "KZR", "L", "LAB", "LAC", "LAD", "LADR", "LAES", "LAFAU", "LAKE", "LAMR", "LAND", "LANDM", "LANDO", "LANDP", "LANV", "LAR", "LARK", "LASE", "LASR", "LATA", "LATAU", "LATAW", "LAUR", "LAW", "LAZ", "LAZR", "LB", "LBGJ", "LBRDA", "LBRDK", "LBRDP", "LBRT", "LBRX", "LBTYA", "LBTYB", "LBTYK", "LC", "LCCC", "LCCCR", "LCFY", "LCFYW", "LCID", "LCII", "LCNB", "LCTX", "LCUT", "LDI", "LDOS", "LDP", "LDWY", "LE", "LEA", "LECO", "LEDS", "LEE", "LEG", "LEGH", "LEGN", "LEGT", "LEN", "LENZ", "LEO", "LESL", "LEU", "LEVI", "LEXX", "LEXXW", "LFCR", "LFMD", "LFMDP", "LFS", "LFST", "LFT", "LFT^A", "LFUS", "LFVN", "LFWD", "LGCB", "LGCL", "LGCY", "LGHL", "LGI", "LGIH", "LGL", "LGN", "LGND", "LGO", "LGPS", "LGVN", "LH", "LHAI", "LHSW", "LHX", "LI", "LICN", "LIDR", "LIDRW", "LIEN", "LIF", "LII", "LILA", "LILAK", "LIMN", "LIN", "LINC",
"LIND", "LINE", "LINK", "LION", "LIQT", "LITB", "LITE", "LITM", "LITS", "LIVE", "LIVN", "LIXT", "LIXTW", "LKFN", "LKQ", "LKSP", "LKSPR", "LKSPU", "LLY", "LLYVA", "LLYVK", "LMAT", "LMB", "LMFA", "LMND", "LMNR", "LMT", "LNAI", "LNC", "LNC^D", "LND", "LNG", "LNKB", "LNKS", "LNN", "LNSR", "LNT", "LNTH", "LNZA", "LNZAW", "LOAN", "LOAR", "LOB", "LOB^A", "LOBO", "LOCL", "LOCO", "LODE", "LOGI", "LOKV", "LOKVU", "LOKVW", "LOMA", "LOOP", "LOPE", "LOT", "LOTWW", "LOVE", "LOW", "LPA", "LPAA", "LPAAW", "LPBB", "LPBBW", "LPCN", "LPG", "LPL", "LPLA", "LPRO", "LPSN", "LPTH", "LPX", "LQDA", "LQDT", "LRCX", "LRE", "LRHC", "LRMR", "LRN", "LSAK", "LSBK", "LSCC", "LSE", "LSF", "LSH", "LSPD", "LSTA", "LSTR", "LTBR", "LTC", "LTCC", "LTH", "LTM", "LTRN", "LTRX", "LTRYW", "LU", "LUCD", "LUCK", "LUCY", "LUCYW", "LUD", "LULU", "LUMN", "LUNG", "LUNR", "LUV", "LUXE", "LVLU", "LVO", "LVRO", "LVROW", "LVS", "LVTX", "LVWR", "LW", "LWAC", "LWACU", "LWACW", "LWAY", "LWLG", "LX", "LXEH", "LXEO", "LXFR", "LXP", "LXP^C", "LXRX", "LXU", "LYB", "LYEL", "LYFT", "LYG", "LYRA", "LYTS", "LYV", "LZ", "LZB", "LZM", "LZMH", "M", "MA", "MAA", "MAA^I", "MAAS", "MAC", "MACI", "MACIW", "MAGH", "MAGN", "MAIA", "MAIN", "MAMA", "MAMK", "MAMO", "MAN", "MANH", "MANU", "MAPS", "MAPSW", "MAR", "MARA", "MARPS", "MAS", "MASI", "MASK", "MASS", "MAT", "MATH", "MATV", "MATW", "MATX", "MAX", "MAXN", "MAYA", "MAYAR", "MAYS", "MAZE", "MB", "MBAV", "MBAVW", "MBBC", "MBC", "MBCN", "MBI", "MBIN", "MBINL", "MBINM", "MBINN", "MBIO", "MBLY", "MBNKO", "MBOT", "MBRX", "MBUU", "MBVI", "MBVIU", "MBVIW", "MBWM", "MBX", "MC", "MCB", "MCBS", "MCD", "MCFT", "MCGA", "MCGAU", "MCGAW", "MCHB", "MCHP", "MCHPP", "MCHX", "MCI", "MCK", "MCN", "MCO", "MCR", "MCRB", "MCRI", "MCRP", "MCS", "MCTR", "MCW", "MCY", "MD", "MDAI", "MDAIW", "MDB", "MDBH", "MDCX", "MDCXW", "MDGL", "MDIA", "MDLZ", "MDRR", "MDT", "MDU", "MDV", "MDV^A", "MDWD", "MDXG", "MDXH", "MEC", "MED", "MEDP", "MEG", "MEGI", "MEGL", "MEHA", "MEI", "MELI", "MENS", "MEOH", "MER^K", "MERC", "MESA", "MESO", "MET", "MET^A", "MET^E", "MET^F", "META", "METC", "METCB", "METCI", "METCZ", "MFA", "MFA^B", "MFA^C", "MFAN", "MFAO", "MFC", "MFG", "MFI", "MFIC", "MFICL", "MFIN", "MFM", "MG", "MGA", "MGEE", "MGF", "MGIC", "MGIH", "MGLD", "MGM", "MGN", "MGNI", "MGNX", "MGPI", "MGR", "MGRB", "MGRC", "MGRD", "MGRE", "MGRT", "MGRX", "MGTX", "MGX", "MGY", "MGYR", "MH", "MHD", "MHF", "MHH", "MHK", "MHLA", "MHN", "MHNC", "MHO", "MHUA", "MI", "MIAX", "MIDD", "MIGI", "MIMI", "MIN", "MIND", "MIR", "MIRA", "MIRM", "MIST", "MITK", "MITN", "MITP", "MITQ", "MITT", "MITT^A", "MITT^B", "MITT^C", "MIY", "MKC", "MKDW", "MKDWW", "MKL", "MKLY", "MKLYR", "MKLYU", "MKSI", "MKTW", "MKTX", "MKZR", "MLAB", "MLAC", "MLACR", "MLCI", "MLCO", "MLEC", "MLECW", "MLGO", "MLI", "MLKN", "MLM", "MLP", "MLR", "MLSS", "MLTX", "MLYS", "MMA", "MMC", "MMD", "MMI", "MMLP", "MMM", "MMS", "MMSI", "MMT", "MMTXU", "MMU", "MMYT", "MNDO", "MNDR", "MNDY", "MNKD", "MNMD", "MNOV", "MNPR", "MNR", "MNRO", "MNSB", "MNSBP", "MNSO", "MNST", "MNTK", "MNTN", "MNTS", "MNTSW", "MNY", "MNYWW", "MO", "MOB", "MOBBW", "MOBX", "MOD", "MODD", "MODG", "MOFG", "MOGO", "MOGU", "MOH", "MOLN", "MOMO", "MORN", "MOS", "MOV", "MOVE", "MP", "MPA", "MPAA", "MPB", "MPC", "MPLT", "MPLX", "MPTI", "MPU", "MPV", "MPW", "MPWR", "MPX", "MQ", "MQT", "MQY", "MRAM", "MRBK", "MRCC", "MRCY", "MREO", "MRK", "MRKR", "MRM", "MRNA", "MRNO", "MRNOW", "MRP", "MRSN", "MRT", "MRTN", "MRUS", "MRVI", "MRVL", "MRX", "MS", "MS^A", "MS^E", "MS^F", "MS^I", "MS^K", "MS^L", "MS^O", "MS^P", "MS^Q", "MSA", "MSAI", "MSAIW", "MSB", "MSBI", "MSBIP", "MSC", "MSCI", "MSD", "MSDL", "MSEX", "MSFT", "MSGE", "MSGM", 
"MSGS", "MSGY", "MSI", "MSIF", "MSM", "MSN", "MSPR", "MSPRW", "MSPRZ", "MSS", "MSTR", "MSW", "MT", "MTA", "MTB", "MTB^H", "MTB^J", "MTB^K", "MTC", "MTCH", "MTD", "MTDR", "MTEK", "MTEKW", "MTEN", "MTEX", "MTG", "MTH", "MTLS", "MTN", "MTNB", "MTR", "MTRN", "MTRX", "MTSI", "MTSR", "MTUS", "MTVA", "MTW", "MTX", "MTZ", "MU", "MUA", "MUC", "MUE", "MUFG", "MUJ", "MUR", "MURA", "MUSA", "MUX", "MVBF", "MVF", "MVIS", "MVO", "MVST", "MVSTW", "MVT", "MWA", "MWG", "MWYN", "MX", "MXC", "MXCT", "MXE", "MXF", "MXL", "MYD", "MYE", "MYFW", "MYGN", "MYI", "MYN", "MYND", "MYNZ", "MYO", "MYPS", "MYPSW", "MYRG", "MYSE", "MYSEW", "MYSZ", "MZTI", "NA", "NAAS", "NABL", "NAC", "NAD", "NAGE", "NAII", "NAK", "NAKA", "NAMI", "NAMM", "NAMMW", "NAMS", "NAMSW", "NAN", "NAOV", "NAT", "NATH", "NATL", "NATR", "NAUT", "NAVI", "NAVN", "NAZ", "NB", "NBB", "NBBK", "NBH", "NBHC", "NBIS", "NBIX", "NBN", "NBP", "NBR", "NBTB", "NBTX", "NBXG", "NBY", "NC", "NCA", "NCDL", "NCEL", "NCEW", "NCI", "NCL", "NCLH", "NCMI", "NCNA", "NCNO", "NCPL", "NCRA", "NCSM", "NCT", "NCTY", "NCV", "NCV^A", "NCZ", "NCZ^A", "NDAQ", "NDLS", "NDMO", "NDRA", "NDSN", "NE", "NEA", "NECB", "NEE", "NEE^N", "NEE^S", "NEE^T", "NEE^U", "NEGG", "NEM", "NEN", "NEO", "NEOG", "NEON", "NEOV", "NEOVW", "NEPH", "NERV", "NESR", "NET", "NETD", "NETDW", "NEU", "NEUP", "NEWP", "NEWT", "NEWTG", "NEWTH", "NEWTI", "NEWTP", "NEWTZ", "NEXA", "NEXM", "NEXN", "NEXT", "NFBK", "NFE", "NFG", "NFGC", "NFJ", "NFLX", "NG", "NGD", "NGG", "NGL", "NGL^B", "NGL^C", "NGNE", "NGS", "NGVC", "NGVT", "NHC", "NHI", "NHICW", "NHPAP", "NHPBP", "NHS", "NHTC", "NI", "NIC", "NICE", "NIE", "NIM", "NINE", "NIO", "NIOBW", "NIPG", "NIQ", "NISN", "NITO", "NIU", "NIVF", "NIVFW", "NIXX", "NIXXW", "NJR", "NKE", "NKLR", "NKSH", "NKTR", "NKTX", "NKX", "NL", "NLOP", "NLY", "NLY^F", "NLY^G", "NLY^I", "NLY^J", "NMAI", "NMAX", "NMCO", "NMFC", "NMFCZ", "NMG", "NMI", "NMIH", "NML", "NMM", "NMP", "NMPAU", "NMR", "NMRA", "NMRK", "NMS", "NMT", "NMTC", "NMZ", "NN", "NNAVW", "NNBR", "NNDM", "NNE", "NNI", "NNN", "NNNN", "NNOX", "NNVC", "NNY", "NOA", "NOAH", "NOC", "NODK", "NOEM", "NOEMR", "NOEMW", "NOG", "NOK", "NOM", "NOMA", "NOMD", "NOTE", "NOTV", "NOV", "NOVT", "NOVTU", "NOW", "NP", "NPAC", "NPACU", "NPACW", "NPB", "NPCE", "NPCT", "NPFD", "NPK", "NPKI", "NPO", "NPT", "NPV", "NPWR", "NQP", "NRC", "NRDS", "NRDY", "NREF", "NREF^A", "NRG", "NRGV", "NRIM", "NRIX", "NRK", "NRO", "NRP", "NRSN", "NRSNW", "NRT", "NRUC", "NRXP", "NRXPW", "NRXS", "NSA", "NSA^A", "NSC", "NSIT", "NSP", "NSPR", "NSRX", "NSSC", "NSTS", "NSYS", "NTAP", "NTB", "NTCL", "NTCT", "NTES", "NTGR", "NTHI", "NTIC", "NTIP", "NTLA", "NTNX", "NTR", "NTRA", "NTRB", "NTRBW", "NTRP", "NTRS", "NTRSO", "NTSK", "NTST", "NTWK", "NTWO", "NTWOW", "NTZ", "NU", "NUAI", "NUAIW", "NUE", "NUKK", "NUKKW", "NUS", "NUTX", "NUV", "NUVB", "NUVL", "NUW", "NUWE", "NVA", "NVAWW", "NVAX", "NVCR", "NVCT", "NVDA", "NVEC", "NVG", "NVGS", "NVMI", "NVNI", "NVNIW", "NVNO", "NVO", "NVR", "NVRI", "NVS", "NVST", "NVT", "NVTS", "NVVE", "NVVEW", "NVX", "NWBI", "NWE", "NWFL", "NWG", "NWGL", "NWL", "NWN", "NWPX", "NWS", "NWSA", "NWTG", "NX", "NXC", "NXDR", "NXDT", "NXDT^A", "NXE", "NXG", "NXGL", "NXGLW", "NXJ", "NXL", "NXN", "NXP", "NXPI", "NXPL", "NXRT", "NXST", "NXT", "NXTC", "NXTT", "NXXT", "NYAX", "NYC", "NYT", "NYXH", "NZF", "O", "OABI", "OABIW", "OACC", "OACCW", "OAK^A", "OAK^B", "OAKU", "OBA", "OBAWW", "OBDC", "OBE", "OBIO", "OBK", "OBLG", "OBT", "OC", "OCC", "OCCI", "OCCIM", "OCCIN", "OCCIO", "OCFC", "OCG", "OCGN", "OCS", "OCSAW", "OCSL", "OCUL", "ODC", "ODD", "ODFL", "ODP", "ODV", "ODVWZ", "ODYS", "OEC", "OESX", "OFAL", "OFG", "OFIX", "OFLX", "OFS", "OFSSH", "OGE",
"OGEN", "OGI", "OGN", "OGS", "OHI", "OI", "OIA", "OII", "OIS", "OKE", "OKLO", "OKTA", "OKUR", "OKYO", "OLB", "OLED", "OLLI", "OLMA", "OLN", "OLP", "OLPX", "OM", "OMAB", "OMC", "OMCC", "OMCL", "OMDA", "OMER", "OMEX", "OMF", "OMH", "OMI", "OMSE", "ON", "ONB", "ONBPO", "ONBPP", "ONC", "ONCH", "ONCHU", "ONCHW", "ONCO", "ONCY", "ONDS", "ONEG", "ONEW", "ONFO", "ONIT", "ONL", "ONMD", "ONMDW", "ONON", "ONTF", "ONTO", "OOMA", "OP", "OPAD", "OPAL", "OPBK", "OPCH", "OPEN", "OPFI", "OPHC", "OPK", "OPP", "OPP^A", "OPP^B", "OPP^C", "OPRA", "OPRT", "OPRX", "OPTT", "OPTX", "OPTXW", "OPXS", "OPY", "OR", "ORA", "ORBS", "ORC", "ORCL", "ORGN", "ORGNW", "ORGO", "ORI", "ORIC", "ORIQ", "ORIQU", "ORIQW", "ORIS", "ORKA", "ORKT", "ORLA", "ORLY", "ORMP", "ORN", "ORRF", "OS", "OSBC", "OSCR", "OSIS", "OSK", "OSPN", "OSRH", "OSRHW", "OSS", "OSTX", "OSUR", "OSW", "OTEX", "OTF", "OTGA", "OTGAU", "OTGAW", "OTIS", "OTLK", "OTLY", "OTTR", "OUST", "OUSTZ", "OUT", "OVBC", "OVID", "OVLY", "OVV", "OWL", "OWLS", "OWLT", "OXBR", "OXBRW", "OXLC", "OXLCG", "OXLCI", "OXLCL", "OXLCN", "OXLCO", "OXLCP", "OXLCZ", "OXM", "OXSQ", "OXSQG", "OXSQH", "OXY", "OYSE", "OYSER", "OYSEU", "OZ", "OZK", "OZKAP", "PAA", "PAAS", "PAC", "PACB", "PACH", "PACHU", "PACHW", "PACK", "PACS", "PAG", "PAGP", "PAGS", "PAHC", "PAI", "PAII", "PAL", "PALI", "PAM", "PAMT", "PANL", "PANW", "PAPL", "PAR", "PARR", "PASG", "PASW", "PATH", "PATK", "PAVM", "PAVS", "PAX", "PAXS", "PAY", "PAYC", "PAYO", "PAYS", "PAYX", "PB", "PBA", "PBBK", "PBF", "PBFS", "PBH", "PBHC", "PBI", "PBI^B", "PBM", "PBMWW", "PBR", "PBT", "PBYI", "PCAP", "PCAPU", "PCAR", "PCB", "PCF", "PCG", "PCG^A", "PCG^B", "PCG^C", "PCG^D", "PCG^E", "PCG^G", "PCG^H", "PCG^I", "PCG^X", "PCH", "PCLA", "PCM", "PCN", "PCOR", "PCQ", "PCRX", "PCSA", "PCSC", "PCT", "PCTTU", "PCTTW", "PCTY", "PCVX", "PCYO", "PD", "PDCC", "PDD", "PDEX", "PDFS", "PDI", "PDLB", "PDM", "PDO", "PDPA", "PDS", "PDSB", "PDT", "PDX", "PDYN", "PDYNW", "PEB", "PEB^E", "PEB^F", "PEB^G", "PEB^H", "PEBK", "PEBO", "PECO", "PED", "PEG", "PEGA", "PELI", "PELIR", "PELIU", "PEN", "PENG", "PENN", "PEO", "PEP", "PEPG", "PERF", "PERI", "PESI", "PETS", "PETZ", "PEW", "PFAI", "PFBC", "PFD", "PFE", "PFG", "PFGC", "PFH", "PFIS", "PFL", "PFLT", "PFN", "PFO", "PFS", "PFSA", "PFSI", "PFX", "PFXNZ", "PG", "PGAC", "PGACR", "PGC", "PGEN", "PGNY", "PGP", "PGR", "PGRE", "PGY", "PGYWW", "PGZ", "PH", "PHAR", "PHAT", "PHG", "PHGE", "PHI", "PHIN", "PHIO", "PHK", "PHM", "PHOE", "PHR", "PHUN", "PHVS", "PHXE^", "PI", "PII", "PIII", "PIIIW", "PIM", "PINC", "PINE", "PINS", "PIPR", "PJT", "PK", "PKBK", "PKE", "PKG", "PKOH", "PKST", "PKX", "PL", "PLAB", "PLAG", "PLAY", "PLBC", "PLBL", "PLBY", "PLCE", "PLD", "PLG", "PLMK", "PLMKW", "PLMR", "PLNT", "PLOW", "PLPC", "PLRX", "PLRZ", "PLSE", "PLTK", "PLTR", "PLUG", "PLUR", "PLUS", "PLUT", "PLX", "PLXS", "PLYM", "PM", "PMAX", "PMCB", "PMEC", "PMI", "PML", "PMM", "PMN", "PMNT", "PMO", "PMT", "PMT^A", "PMT^B", "PMT^C", "PMTR", "PMTRU", "PMTRW", "PMTS", "PMTU", "PMTV", "PMTW", "PMVP", "PN", "PNBK", "PNC", "PNFP", "PNFPP", "PNI", "PNNT", "PNR", "PNRG", "PNTG", "PNW", "POAI", "POAS", "POCI", "PODC", "PODD", "POET", "POLA", "POLE", "POLEU", "POLEW", "POM", "PONY", "POOL", "POR", "POST", "POWI", "POWL", "POWW", "POWWP", "PPBT", "PPC", "PPCB", "PPG", "PPIH", "PPL", "PPSI", "PPT", "PPTA", "PR", "PRA", "PRAA", "PRAX", "PRCH", "PRCT", "PRDO", "PRE", "PRENW", "PRFX", "PRG", "PRGO", "PRGS", "PRH", "PRHI", "PRHIZ", "PRI", "PRIF^D", "PRIF^J", "PRIF^K", "PRIF^L", "PRIM", "PRK", "PRKS", "PRLB", "PRLD", "PRM", "PRMB", "PRME", "PRO", "PROF", "PROK", "PROP", "PROV", "PRPH", "PRPL", "PRPO", "PRQR", "PRS", "PRSO", "PRSU", "PRT", 
"PRTA", "PRTC", "PRTH", "PRTS", "PRU", "PRVA", "PRZO", "PSA", "PSA^F", "PSA^G", "PSA^H", "PSA^I", "PSA^J", "PSA^K", "PSA^L", "PSA^M", "PSA^N", "PSA^O", "PSA^P", "PSA^Q", "PSA^R", "PSA^S", "PSBD", "PSEC", "PSEC^A", "PSF", "PSFE", "PSHG", "PSIG", "PSIX", "PSKY", "PSMT", "PSN", "PSNL", "PSNY", "PSNYW", "PSO", "PSQH", "PSTG", "PSTL", "PSTV", "PSX", "PT", "PTA", "PTC", "PTCT", "PTEN", "PTGX", "PTHL", "PTHS", "PTIX", "PTIXW", "PTLE", "PTLO", "PTN", "PTON", "PTRN", "PTY", "PUBM", "PUK", "PULM", "PUMP", "PVBC", "PVH", "PVL", "PVLA", "PW", "PW^A", "PWP", "PWR", "PX", "PXED", "PXLW", "PXS", "PYPD", "PYPL", "PYT", "PYXS", "PZG", "PZZA", "Q", "QBTS", "QCLS", "QCOM", "QCRH", "QD", "QDEL", "QETA", "QETAR", "QFIN", "QGEN", "QH", "QIPT", "QLGN", "QLYS", "QMCO", "QNCX", "QNRX", "QNST", "QNTM", "QQQX", "QRHC", "QRVO", "QS", "QSEA", "QSI", "QSIAW", "QSR", "QTRX", "QTTB", "QTWO", "QUAD", "QUBT", "QUIK", "QUMS", "QUMSR", "QUMSU", "QURE", "QVCC", "QVCD", "QVCGA", "QVCGP", "QXO", "QXO^B", "R", "RA", "RAAQ", "RAAQU", "RAAQW", "RAC", "RAC/WS", "RACE", "RADX", "RAIL", "RAIN", "RAINW", "RAL", "RAMP", "RAND", "RANG", "RANGR", "RANI", "RAPP", "RAPT", "RARE", "RAVE", "RAY", "RAYA", "RBA", "RBB", "RBBN", "RBC", "RBCAA", "RBKB", "RBLX", "RBNE", "RBOT", "RBRK", "RC", "RC^C", "RC^E", "RCAT", "RCB", "RCC", "RCD", "RCEL", "RCG", "RCI", "RCKT", "RCKY", "RCL", "RCMT", "RCON", "RCS", "RCT", "RCUS", "RDAC", "RDACR", "RDACU", "RDAG", "RDAGU", "RDAGW", "RDCM", "RDDT", "RDGT", "RDHL", "RDI", "RDIB", "RDN", "RDNT", "RDNW", "RDVT", "RDW", "RDWR", "RDY", "RDZN", "RDZNW", "REAL", "REAX", "REBN", "RECT", "REE", "REFI", "REFR", "REG", "REGCO", "REGCP", "REGN", "REI", "REKR", "RELI", "RELIW", "RELL", "RELX", "RELY", "RENT", "REPL", "REPX", "RERE", "RES", "RETO", "REVB", "REVBW", "REVG", "REX", "REXR", "REXR^B", "REXR^C", "REYN", "REZI", "RF", "RF^C", "RF^E", "RF^F", "RFAI", "RFAIR", "RFI", "RFIL", "RFL", "RFM", "RFMZ", "RGA", "RGC", "RGCO", "RGEN", "RGLD", "RGNX", "RGP", "RGR", "RGS", "RGT", "RGTI", "RGTIW", "RH", "RHI", "RHLD", "RHP", "RIBB", "RIBBU", "RICK", "RIG", "RIGL", "RILY", "RILYG", "RILYK", "RILYL", "RILYN", "RILYP", "RILYT", "RILYZ", "RIME", "RIO", "RIOT", "RITM", "RITM^A", "RITM^B", "RITM^C", "RITM^D", "RITM^E", "RITR", "RIV", "RIV^A", "RIVN", "RJF", "RJF^B", "RKDA", "RKLB", "RKT", "RL", "RLAY", "RLGT", "RLI", "RLJ", "RLJ^A", "RLMD", "RLTY", "RLX", "RLYB", "RM", "RMAX", "RMBI", "RMBS", "RMCF", "RMCO", "RMCOW", "RMD", "RMI", "RMM", "RMMZ", "RMNI", "RMR", "RMSG", "RMSGW", "RMT", "RMTI", "RNA", "RNAC", "RNAZ", "RNG", "RNGR", "RNGTU", "RNP", "RNR", "RNR^F", "RNR^G", "RNST", "RNTX", "RNW", "RNWWW", "RNXT", "ROAD", "ROCK", "ROG", "ROIV", "ROK", "ROKU", "ROL", "ROLR", "ROMA", "ROOT", "ROP", "ROST", "RPAY", "RPD", "RPGL", "RPID", "RPM", "RPRX", "RPT", "RPT^C", "RPTX", "RQI", "RR", "RRBI", "RRC", "RRGB", "RRR", "RRX", "RS", "RSF", "RSG", "RSI", "RSKD", "RSSS", "RSVR", "RSVRW", "RTAC", "RTACU", "RTACW", "RTO", "RTX", "RUBI", "RUM", "RUMBW", "RUN", "RUSHA", "RUSHB", "RVLV", "RVMD", "RVMDW", "RVP", "RVPH", "RVPHW", "RVSB", "RVSN", "RVSNW", "RVT", "RVTY", "RVYL", "RWAY", "RWAYL", "RWAYZ", "RWT", "RWT^A", "RWTN", "RWTO", "RWTP", "RXO", "RXRX", "RXST", "RXT", "RY", "RYAAY", "RYAM", "RYAN", "RYDE", "RYET", "RYI", "RYM", "RYN", "RYOJ", "RYTM", "RZB", "RZC", "RZLT", "RZLV", "RZLVW", "S", "SA", "SABA", "SABR", "SABS", "SABSW", "SACH", "SACH^A", "SAFE", "SAFT", "SAFX", "SAGT", "SAH", "SAIA", "SAIC", "SAIH", "SAIHW", "SAIL", "SAJ", "SAM", "SAMG", "SAN", "SANA", "SANG", "SANM", "SAP", "SAR", "SARO", "SAT", "SATA", "SATL", "SATLW", "SATS", "SAVA", "SAY", "SAZ", "SB", "SB^C", "SB^D", "SBAC", "SBC", "SBCF", "SBCWW", "SBDS",
"SBET", "SBEV", "SBFG", "SBFM", "SBGI", "SBH", "SBI", "SBLK", "SBLX", "SBR", "SBRA", "SBS", "SBSI", "SBSW", "SBUX", "SBXD", "SCAG", "SCCD", "SCCE", "SCCF", "SCCG", "SCCO", "SCD", "SCE^G", "SCE^J", "SCE^K", "SCE^L", "SCE^M", "SCE^N", "SCHL", "SCHW", "SCHW^D", "SCHW^J", "SCI", "SCKT", "SCL", "SCLX", "SCLXW", "SCM", "SCNI", "SCNX", "SCOR", "SCS", "SCSC", "SCVL", "SCWO", "SCYX", "SD", "SDA", "SDAWW", "SDGR", "SDHC", "SDHI", "SDHIR", "SDHIU", "SDHY", "SDOT", "SDRL", "SDST", "SDSTW", "SE", "SEAL^A", "SEAL^B", "SEAT", "SEATW", "SEB", "SEDG", "SEE", "SEED", "SEER", "SEG", "SEGG", "SEI", "SEIC", "SELF", "SELX", "SEM", "SEMR", "SENEA", "SENEB", "SENS", "SEPN", "SER", "SERA", "SERV", "SES", "SEV", "SEVN", "SEVNR", "SEZL", "SF", "SF^B", "SF^C", "SF^D", "SFB", "SFBC", "SFBS", "SFD", "SFHG", "SFIX", "SFL", "SFM", "SFNC", "SFST", "SFWL", "SG", "SGA", "SGBX", "SGC", "SGD", "SGHC", "SGHT", "SGI", "SGLY", "SGML", "SGMO", "SGMT", "SGN", "SGRP", "SGRY", "SGU", "SHAK", "SHBI", "SHC", "SHCO", "SHEL", "SHEN", "SHFS", "SHFSW", "SHG", "SHIM", "SHIP", "SHLS", "SHMD", "SHMDW", "SHO", "SHO^H", "SHO^I", "SHOO", "SHOP", "SHPH", "SHW", "SI", "SIBN", "SID", "SIDU", "SIEB", "SIF", "SIFY", "SIG", "SIGA", "SIGI", "SIGIP", "SII", "SILA", "SILC", "SILO", "SIM", "SIMA", "SIMAW", "SIMO", "SINT", "SION", "SIRI", "SITC", "SITE", "SITM", "SJ", "SJM", "SJT", "SKBL", "SKE", "SKIL", "SKIN", "SKK", "SKLZ", "SKM", "SKT", "SKWD", "SKY", "SKYE", "SKYH", "SKYQ", "SKYT", "SKYW", "SKYX", "SLAB", "SLAI", "SLB", "SLDB", "SLDE", "SLDP", "SLDPW", "SLE", "SLF", "SLG", "SLG^I", "SLGB", "SLGL", "SLGN", "SLI", "SLM", "SLMBP", "SLMT", "SLN", "SLND", "SLNG", "SLNH", "SLNHP", "SLNO", "SLP", "SLQT", "SLRC", "SLRX", "SLS", "SLSN", "SLSR", "SLVM", "SLXN", "SLXNW", "SM", "SMA", "SMBC", "SMBK", "SMC", "SMCI", "SMFG", "SMG", "SMHI", "SMID", "SMLR", "SMMT", "SMRT", "SMSI", "SMTC", "SMTI", "SMTK", "SMWB", "SMX", "SMXT", "SMXWW", "SN", "SNA", "SNAL", "SNAP", "SNBR", "SNCR", "SNCY", "SND", "SNDA", "SNDK", "SNDL", "SNDR", "SNDX", "SNES", "SNEX", "SNFCA", "SNGX", "SNN", "SNOA", "SNOW", "SNPS", "SNSE", "SNT", "SNTG", "SNTI", "SNV", "SNV^D", "SNV^E", "SNWV", "SNX", "SNY", "SNYR", "SO", "SOAR", "SOBO", "SOBR", "SOC", "SOCA", "SOCAW", "SOFI", "SOGP", "SOHO", "SOHOB", "SOHON", "SOHOO", "SOHU", "SOJC", "SOJD", "SOJE", "SOJF", "SOL", "SOLS", "SOLV", "SOMN", "SON", "SOND", "SONDW", "SONM", "SONN", "SONO", "SONY", "SOPA", "SOPH", "SOR", "SORA", "SOS", "SOTK", "SOUL", "SOUN", "SOUNW", "SOWG", "SPAI", "SPB", "SPCB", "SPCE", "SPE", "SPE^C", "SPEG", "SPEGR", "SPEGU", "SPFI", "SPG", "SPG^J", "SPGI", "SPH", "SPHL", "SPHR", "SPIR", "SPKL", "SPKLW", "SPMA", "SPMC", "SPME", "SPNS", "SPNT", "SPNT^B", "SPOK", "SPOT", "SPPL", "SPR", "SPRB", "SPRC", "SPRO", "SPRU", "SPRY", "SPSC", "SPT", "SPWH", "SPWR", "SPWRW", "SPXC", "SPXX", "SQFT", "SQFTP", "SQFTW", "SQM", "SQNS", "SR", "SR^A", "SRAD", "SRBK", "SRCE", "SRDX", "SRE", "SREA", "SRFM", "SRG", "SRG^A", "SRI", "SRL", "SRPT", "SRRK", "SRTA", "SRTAW", "SRTS", "SRV", "SRXH", "SRZN", "SRZNW", "SSB", "SSBI", "SSD", "SSEA", "SSEAU", "SSII", "SSKN", "SSL", "SSM", "SSNC", "SSP", "SSRM", "SSSS", "SSSSL", "SST", "SSTI", "SSTK", "SSYS", "ST", "STAA", "STAG", "STAI", "STAK", "STBA", "STC", "STE", "STEC", "STEL", "STEM", "STEP", "STEW", "STEX", "STFS", "STG", "STGW", "STHO", "STI", "STIM", "STK", "STKE", "STKH", "STKL", "STKS", "STLA", "STLD", "STM", "STN", "STNE", "STNG", "STOK", "STRA", "STRC", "STRD", "STRF", "STRK", "STRL", "STRO", "STRR", "STRRP", "STRS", "STRT", "STRW", "STRZ", "STSS", "STSSW", "STT", "STT^G", "STTK", "STUB", "STVN", "STWD", "STX", "STXS", "STZ", "SU", "SUGP", "SUI", "SUIG", "SUN", "SUNC", "SUNE", 
"SUNS", "SUPN", "SUPV", "SUPX", "SURG", "SUUN", "SUZ", "SVAC", "SVACU", "SVC", "SVCCU", "SVCCW", "SVCO", "SVM", "SVRA", "SVRE", "SVREW", "SVV", "SW", "SWAG", "SWAGW", "SWBI", "SWIM", "SWK", "SWKH", "SWKHL", "SWKS", "SWVL", "SWVLW", "SWX", "SWZ", "SXC", "SXI", "SXT", "SXTC", "SXTP", "SXTPW", "SY", "SYBT", "SYBX", "SYF", "SYF^A", "SYF^B", "SYK", "SYM", "SYNA", "SYNX", "SYPR", "SYRE", "SYY", "SZZL", "SZZLR", "SZZLU", "T", "T^A", "T^C", "TAC", "TACH", "TACHU", "TACHW", "TACO", "TACOU", "TACOW", "TACT", "TAIT", "TAK", "TAL", "TALK", "TALKW", "TALO", "TANH", "TAOP", "TAOX", "TAP", "TARA", "TARS", "TASK", "TATT", "TAVI", "TAYD", "TBB", "TBBB", "TBBK", "TBCH", "TBH", "TBHC", "TBI", "TBLA", "TBLAW", "TBLD", "TBMC", "TBMCR", "TBN", "TBPH", "TBRG", "TC", "TCBI", "TCBIO", "TCBK", "TCBS", "TCBX", "TCGL", "TCI", "TCMD", "TCOM", "TCPA", "TCPC", "TCRT", "TCRX", "TCX", "TD", "TDAC", "TDACW", "TDC", "TDF", "TDG", "TDIC", "TDOC", "TDS", "TDS^U", "TDS^V", "TDTH", "TDUP", "TDW", "TDWDU", "TDY", "TE", "TEAD", "TEAM", "TECH", "TECK", "TECTP", "TECX", "TEF", "TEI", "TEL", "TELA", "TELO", "TEM", "TEN", "TEN^E", "TEN^F", "TENB", "TENX", "TEO", "TER", "TERN", "TEVA", "TEX", "TFC", "TFC^I", "TFC^O", "TFC^R", "TFII", "TFIN", "TFIN^", "TFPM", "TFSA", "TFSL", "TFX", "TG", "TGB", "TGE", "TGEN", "TGHL", "TGL", "TGLS", "TGNA", "TGS", "TGT", "TGTX", "TH", "THAR", "THC", "THCH", "THFF", "THG", "THH", "THM", "THO", "THQ", "THR", "THRM", "THRY", "THS", "THW", "TIC", "TIGO", "TIGR", "TIL", "TILE", "TIMB", "TIPT", "TIRX", "TISI", "TITN", "TIVC", "TJX", "TK", "TKC", "TKLF", "TKNO", "TKO", "TKR", "TLF", "TLIH", "TLK", "TLN", "TLNC", "TLNCU", "TLNCW", "TLPH", "TLRY", "TLS", "TLSA", "TLSI", "TLSIW", "TLX", "TLYS", "TM", "TMC", "TMCI", "TMCWW", "TMDE", "TMDX", "TME", "TMHC", "TMO", "TMP", "TMQ", "TMUS", "TMUSI", "TMUSL", "TMUSZ", "TNC", "TNDM", "TNET", "TNGX", "TNK", "TNL", "TNMG", "TNON", "TNONW", "TNXP", "TNYA", "TOI", "TOIIW", "TOL", "TOMZ", "TONX", "TOON", "TOP", "TOPP", "TOPS", "TORO", "TOST", "TOUR", "TOVX", "TOWN", "TOYO", "TPB", "TPC", "TPCS", "TPET", "TPG", "TPGXL", "TPH", "TPL", "TPR", "TPST", "TPTA", "TPVG", "TR", "TRAK", "TRAW", "TRC", "TRDA", "TREE", "TREX", "TRGP", "TRI", "TRIB", "TRIN", "TRINI", "TRINZ", "TRIP", "TRMB", "TRMD", "TRMK", "TRN", "TRNO", "TRNR", "TRNS", "TRON", "TROO", "TROW", "TROX", "TRP", "TRS", "TRSG", "TRST", "TRT", "TRTN^A", "TRTN^B", "TRTN^C", "TRTN^D", "TRTN^E", "TRTN^F", "TRTX", "TRTX^C", "TRU", "TRUE", "TRUG", "TRUP", "TRV", "TRVG", "TRVI", "TRX", "TS", "TSAT", "TSBK", "TSCO", "TSE", "TSEM", "TSHA", "TSI", "TSLA", "TSLX", "TSM", "TSN", "TSQ", "TSSI", "TT", "TTAM", "TTAN", "TTC", "TTD", "TTE", "TTEC", "TTEK", "TTGT", "TTI", "TTMI", "TTRX", "TTSH", "TTWO", "TU", "TURB", "TUSK", "TUYA", "TV", "TVA", "TVACU", "TVACW", "TVAI", "TVC", "TVE", "TVGN", "TVGNW", "TVRD", "TVTX", "TW", "TWFG", "TWG", "TWI", "TWIN", "TWLO", "TWN", "TWNP", "TWO", "TWO^A", "TWO^B", "TWO^C", "TWOD", "TWST", "TX", "TXG", "TXMD", "TXN", "TXNM", "TXO", "TXRH", "TXT", "TY", "TY^", "TYG", "TYGO", "TYL", "TYRA", "TZOO", "TZUP", "U", "UA", "UAA", "UAL", "UAMY", "UAN", "UAVS", "UBCP", "UBER", "UBFO", "UBS", "UBSI", "UBXG", "UCAR", "UCB", "UCL", "UCTT", "UDMY", "UDR", "UE", "UEC", "UEIC", "UFCS", "UFG", "UFI", "UFPI", "UFPT", "UG", "UGI", "UGP", "UGRO", "UHAL", "UHG", "UHGWW", "UHS", "UHT", "UI", "UIS", "UK", "UKOMW", "UL", "ULBI", "ULCC", "ULH", "ULS", "ULTA", "ULY", "UMAC", "UMBF", "UMBFO", "UMC", "UMH", "UMH^D", "UNB", "UNCY", "UNF", "UNFI", "UNH", "UNIT", "UNM", "UNMA", "UNP", "UNTY", "UOKA", "UONE", "UONEK", "UP", "UPB", "UPBD", "UPC", "UPLD", "UPS", "UPST", "UPWK", "UPXI", "URBN", "URG", "URGN", "URI", 
"UROY", "USA", "USAC", "USAR", "USARW", "USAS", "USAU", "USB", "USB^A", "USB^H", "USB^P", "USB^Q", "USB^R", "USB^S", "USBC", "USCB", "USEA", "USEG", "USFD", "USGO", "USGOW", "USIO", "USLM", "USNA", "USPH", "UTF", "UTG", "UTHR", "UTI", "UTL", "UTMD", "UTSI", "UTZ", "UUU", "UUUU", "UVE", "UVSP", "UVV", "UWMC", "UXIN", "UYSC", "UYSCR", "UZD", "UZE", "UZF", "V", "VABK", "VAC", "VACH", "VACHW", "VAL", "VALE", "VALN", "VALU", "VANI", "VATE", "VBF", "VBIX", "VBNK", "VC", "VCEL", "VCIC", "VCICU", "VCICW", "VCIG", "VCTR", "VCV", "VCYT", "VECO", "VEEA", "VEEAW", "VEEE", "VEEV", "VEL", "VELO", "VENU", "VEON", "VERA", "VERI", "VERO", "VERU", "VERX", "VET", "VFC", "VFF", "VFL", "VFS", "VG", "VGAS", "VGI", "VGM", "VGZ", "VHC", "VHI", "VIA", "VIASP", "VIAV", "VICI", "VICR", "VIK", "VINP", "VIOT", "VIPS", "VIR", "VIRC", "VIRT", "VIST", "VITL", "VIV", "VIVK", "VIVS", "VKI", "VKQ", "VKTX", "VLGEA", "VLN", "VLO", "VLRS", "VLT", "VLTO", "VLY", "VLYPN", "VLYPO", "VLYPP", "VMAR", "VMC", "VMD", "VMEO", "VMI", "VMO", "VNCE", "VNDA", "VNET", "VNME", "VNMEU", "VNO", "VNO^L", "VNO^M", "VNO^N", "VNO^O", "VNOM", "VNRX", "VNT", "VNTG", "VOC", "VOD", "VOR", "VOXR", "VOYA", "VOYA^B", "VOYG", "VPG", "VPV", "VRA", "VRAR", "VRAX", "VRCA", "VRDN", "VRE", "VREX", "VRM", "VRME", "VRNS", "VRNT", "VRRM", "VRSK", "VRSN", "VRT", "VRTS", "VRTX", "VS", "VSA", "VSAT", "VSCO", "VSEC", "VSEE", "VSEEW", "VSH", "VSME", "VSSYW", "VST", "VSTA", "VSTD", "VSTM", "VSTS", "VTAK", "VTEX", "VTGN", "VTLE", "VTMX", "VTN", "VTOL", "VTR", "VTRS", "VTS", "VTSI", "VTVT", "VTYX", "VUZI", "VVOS", "VVPR", "VVR", "VVV", "VVX", "VWAV", "VWAVW", "VYGR", "VYNE", "VYX", "VZ", "VZLA", "W", "WAB", "WABC", "WAFD", "WAFDP", "WAFU", "WAI", "WAL", "WAL^A", "WALD", "WALDW", "WASH", "WAT", "WATT", "WAVE", "WAY", "WB", "WBD", "WBI", "WBS", "WBS^F", "WBS^G", "WBTN", "WBUY", "WBX", "WCC", "WCN", "WCT", "WD", "WDAY", "WDC", "WDFC", "WDH", "WDI", "WDS", "WEA", "WEAV", "WEC", "WELL", "WEN", "WENN", "WENNU", "WERN", "WES", "WEST", "WETH", "WETO", "WEX", "WEYS", "WF", "WFC", "WFC^A", "WFC^C", "WFC^D", "WFC^L", "WFC^Y", "WFC^Z", "WFCF", "WFF", "WFG", "WFRD", "WGO", "WGRX", "WGS", "WGSWW", "WH", "WHD", "WHF", "WHFCL", "WHG", "WHLR", "WHLRD", "WHLRL", "WHLRP", "WHR", "WHWK", "WIA", "WILC", "WIMI", "WINA", "WING", "WIT", "WIW", "WIX", "WK", "WKC", "WKEY", "WKHS", "WKSP", "WLAC", "WLACU", "WLACW", "WLDN", "WLDS", "WLDSW", "WLFC", "WLK", "WLKP", "WLY", "WLYB", "WM", "WMB", "WMG", "WMK", "WMS", "WMT", "WNC", "WNEB", "WNW", "WOK", "WOLF", "WOOF", "WOR", "WORX", "WOW", "WPC", "WPM", "WPP", "WPRT", "WRAP", "WRB", "WRB^E", "WRB^F", "WRB^G", "WRB^H", "WRBY", "WRD", "WRLD", "WRN", "WS", "WSBC", "WSBCO", "WSBCP", "WSBF", "WSBK", "WSC", "WSFS", "WSM", "WSO", "WSO/B", "WSR", "WST", "WSTNU", "WT", "WTBA", "WTF", "WTFC", "WTFCN", "WTGUR", "WTI", "WTM", "WTO", "WTRG", "WTS", "WTTR", "WTW", "WU", "WULF", "WVE", "WVVI", "WVVIP", "WW", "WWD", "WWR", "WWW", "WXM", "WY", "WYFI", "WYHG", "WYNN", "WYY", "XAIR", "XBIO", "XBIT", "XBP", "XBPEW", "XCH", "XCUR", "XEL", "XELB", "XELLL", "XENE", "XERS", "XFLT", "XFOR", "XGN", "XHG", "XHLD", "XHR", "XIFR", "XLO", "XMTR", "XNCR", "XNET", "XOM", "XOMA", "XOMAO", "XOMAP", "XOS", "XOSWW", "XP", "XPEL", "XPER", "XPEV", "XPL", "XPO", "XPOF", "XPON", "XPRO", "XRAY", "XRPC", "XRPN", "XRPNU", "XRPNW", "XRTX", "XRX", "XTIA", "XTKG", "XTLB", "XTNT", "XWEL", "XWIN", "XXII", "XYF", "XYL", "XYZ", "XZO", "YAAS", "YALA", "YB", "YCBD", "YCY", "YDDL", "YDES", "YDESW", "YDKG", "YELP", "YETI", "YEXT", "YGMZ", "YHC", "YHGJ", "YHNA", "YHNAR", "YI", "YIBO", "YJ", "YMAT", "YMM", "YMT", "YORW", "YOU", "YOUL", "YPF", "YQ", "YRD", "YSG", "YSXT", "YTRA", 
"YUM", "YUMC", "YXT", "YYAI", "YYGH", "Z", "ZBAI", "ZBAO", "ZBH", "ZBIO", "ZBRA", "ZCMD", "ZD", "ZDAI", "ZDGE", "ZENA", "ZENV", "ZEO", "ZEOWW", "ZEPP", "ZETA", "ZEUS", "ZG", "ZGM", "ZGN", "ZH", "ZIM", "ZION", "ZIONP", "ZIP", "ZJK", "ZJYL", "ZK", "ZKH", "ZKIN", "ZLAB", "ZM", "ZNB", "ZNTL", "ZONE", "ZOOZ", "ZOOZW", "ZS", "ZSPC", "ZTEK", "ZTO", "ZTR", "ZTS", "ZUMZ", "ZURA", "ZVIA", "ZVRA", "ZWS", "ZYBT", "ZYME", "ZYXI",

#US500
"A", "AAPL", "ABBV", "ABNB", "ABT", "ACGL", "ACN", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEE", "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM", "ALB", "ALGN", "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME", "AMGN", "AMP", "AMT", "AMZN", "ANET", "AON", "AOS", "APA", "APD", "APH", "APO", "APP", "APTV", "ARE", "ATO", "AVB", "AVGO", "AVY", "AWK", "AXON", "AXP", "AZO", "BA", "BAC", "BALL", "BAX", "BBY", "BDX", "BEN", "BF.B", "BG", "BIIB", "BK", "BKNG", "BKR", "BLDR", "BLK", "BMY", "BR", "BRK.B", "BRO", "BSX", "BX", "BXP", "C", "CAG", "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE", "CCI", "CCL", "CDNS", "CDW", "CEG", "CF", "CFG", "CHD", "CHRW", "CHTR", "CI", "CINF", "CL", "CLX", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC", "CNP", "COF", "COIN", "COO", "COP", "COR", "COST", "CPAY", "CPB", "CPRT", "CPT", "CRL", "CRM", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTRA", "CTSH", "CTVA", "CVS", "CVX", "D", "DAL", "DASH", "DAY", "DD", "DDOG", "DE", "DECK", "DELL", "DG", "DGX", "DHI", "DHR", "DIS", "DLR", "DLTR", "DOC", "DOV", "DOW", "DPZ", "DRI", "DTE", "DUK", "DVA", "DVN", "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EG", "EIX", "EL", "ELV", "EME", "EMR", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ERIE", "ES", "ESS", "ETN", "ETR", "EVRG", "EW", "EXC", "EXE", "EXPD", "EXPE", "EXR", "F", "FANG", "FAST", "FCX", "FDS", "FDX", "FE", "FFIV", "FISV", "FICO", "FIS", "FITB", "FOX", "FOXA", "FRT", "FSLR", "FTNT", "FTV", "GD", "GDDY", "GE", "GEHC", "GEN", "GEV", "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GOOG", "GOOGL", "GPC", "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "HIG", "HII", "HLT", "HOLX", "HON", "HOOD", "HPE", "HPQ", "HRL", "HSIC", "HST", "HSY", "HUBB", "HUM", "HWM", "IBKR", "IBM", "ICE", "IDXX", "IEX", "IFF", "INCY", "INTC", "INTU", "INVH", "IP", "IPG", "IQV", "IR", "IRM", "ISRG", "IT", "ITW", "IVZ", "J", "JBHT", "JBL", "JCI", "JKHY", "JNJ", "JPM", "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KKR", "KLAC", "KMB", "KMI", "KO", "KR", "KVUE", "L", "LDOS", "LEN", "LH", "LHX", "LII", "LIN", "LKQ", "LLY", "LMT", "LNT", "LOW", "LRCX", "LULU", "LUV", "LVS", "LW", "LYB", "LYV", "MA", "MAA", "MAR", "MAS", "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MET", "META", "MGM", "MHK", "MKC", "MLM", "MMC", "MMM", "MNST", "MO", "MOH", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MS", "MSCI", "MSFT", "MSI", "MTB", "MTCH", "MTD", "MU", "NCLH", "NDAQ", "NDSN", "NEE", "NEM", "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP", "NTRS", "NUE", "NVDA", "NVR", "NWS", "NWSA", "NXPI", "O", "ODFL", "OKE", "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY", "PANW", "PAYC", "PAYX", "PCAR", "PCG", "PEG", "PEP", "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PLD", "PLTR", "PM", "PNC", "PNR", "PNW", "PODD", "POOL", "PPG", "PPL", "PRU", "PSA", "PSKY", "PSX", "PTC", "PWR", "PYPL", "Q", "QCOM", "RCL", "REG", "REGN", "RF", "RJF", "RL", "RMD", "ROK", "ROL", "ROP", "ROST", "RSG", "RTX", "RVTY", "SBAC", "SBUX", "SCHW", "SHW", "SJM", "SLB", "SMCI", "SNA", "SNPS", "SO", "SOLS", "SOLV", "SPG", "SPGI", "SRE", "STE", "STLD", "STT", "STX", "STZ", "SW", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP", "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TGT", "TJX", "TKO", "TMO", "TMUS", "TPL", "TPR", "TRGP", "TRMB", "TROW", "TRV", "TSCO", "TSLA", "TSN", "TT", "TTD", "TTWO", "TXN", "TXT", "TYL", "UAL", "UBER", "UDR", "UHS", "ULTA", "UNH", "UNP", "UPS", "URI", "USB", "V", "VICI", "VLO", "VLTO", "VMC", "VRSK", "VRSN", "VRTX", "VST", "VTR", "VTRS", "VZ", "WAB", "WAT", "WBD", "WDAY", "WDC", "WEC", "WELL", "WFC", "WM", "WMB", "WMT", "WRB", "WSM", "WST", "WTW", "WY", "WYNN", "XEL", "XOM", "XYL", "XYZ", "YUM", "ZBH", "ZBRA", "ZTS",

#US30
"AMGN", "AMZN", "CRM", "CVX", "DIS", "GS", "HD", "IBM", "JNJ", "JPM", "MCD", "MMM", "MRK", "NKE", "PG", "TRV", "UNH", "VZ", "WMT", "V", "KO", "SHW", "AXP", "BA", "CAT", "CSCO", "AAPL", "HON", "MSFT", "NVDA",

#Sectors
"XLY", "IWM", "DIA", "SPY", "XLI", "QQQ", "XLK", "SMH", "XLRE", "XLE", "KRE", "DXY", "GDX", "XLP", "XLF", "XLU", "XLV",

#ETFS
"EWA", "EWC", "EWG", "EWH", "EWJ", "EWL", "EWM", "EWP", "EWS", "EWT", "EWU", "EWW", "EWY", "EWZ", "EZA", "FXI", "DXJ", "EPI", "PIN", "IDX", "EWI", "XAR", "XSD", "BLCN", "ROKT", "CRAK", "PSI", "IEO", "FTXL", "ARKK", "QTUM", "PRN", "ARKW", "PPA", "BLOK", "ITA", "SOXX", "PKB", "CSD", "FPX", "FITE", "ECH", "EZA", "QMOM", "SLX", "JSMD", "AIRR", "URA", "PEXL", "JSML", "RSPG", "COPX", "GRPM", "IDX", "SMH", "SIXG", "FNY", "COLO", "XNTK", "GRID", "XMMO", "QLD", "NANR", "RFV", "SPHB", "PSCI", "CARZ", "RING", "CHIQ", "VFMO", "FYC", "XMHQ", "PAVE", "VDE", "PIZ", "XME", "FAD", "ROBO", "SMLF", "RZV", "EPU", "IXC", "AIA", "IDOG", "FTEC", "XLE", "PICK", "VGT", "USCI", "XLK", "SDCI", "FDD", "VOT", "IGM", "AADR", "RWK", "BFOR", "FTGC", "EQRR", "PRFZ", "IWP", "IYW", "VB", "ISCF", "PSC", "GDX", "QGRO", "GVAL", "GSSC", "FNDE", "FDMO", "IETC", "PXH", "IJJ", "EFAS", "EMQQ", "RWJ", "EYLD", "JHMM", "RAAX", "OMFS",
]

# Score configuration per asset class (price, flow, fundamentals)
SCORES_CONFIG = {
    "EQUITY": {"price": 0.40, "flow": 0.35, "fund": 0.25},
    "ETF": {"price": 0.45, "flow": 0.45, "fund": 0.10},
    "INDEX": {"price": 0.70, "flow": 0.00, "fund": 0.30},
    "COMMODITY": {"price": 0.80, "flow": 0.20, "fund": 0.00},
    "CRYPTOCURRENCY": {"price": 0.75, "flow": 0.25, "fund": 0.00},
    "CURRENCY": {"price": 0.80, "flow": 0.20, "fund": 0.00},
    "UNKNOWN": {"price": 0.40, "flow": 0.35, "fund": 0.25}
}

# -----------------------------
# Helpers: indicators & utils
# -----------------------------
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(period, min_periods=period).mean()
    ma_down = down.rolling(period, min_periods=period).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def compute_obv(df):
    obv = [0]
    for i in range(1, len(df)):
        if df['Close'].iat[i] > df['Close'].iat[i-1]:
            obv.append(obv[-1] + int(df['Volume'].iat[i]) if 'Volume' in df.columns else obv[-1])
        elif df['Close'].iat[i] < df['Close'].iat[i-1]:
            obv.append(obv[-1] - int(df['Volume'].iat[i]) if 'Volume' in df.columns else obv[-1])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=df.index)

def safe_div(a,b,default=np.nan):
    try:
        return a/b if b else default
    except Exception:
        return default

# -----------------------------
# Asset class & sector detection
# -----------------------------
def detect_asset_class(ticker):
    if isinstance(ticker, str):
        if ticker.endswith("=X"):
            return "CURRENCY"
        if ticker.endswith("=F") or ticker.endswith("=f"):
            return "COMMODITY"
        if ticker.endswith("-USD"):
            return "CRYPTOCURRENCY"
        if ticker.startswith("^"):
            return "INDEX"
    try:
        info = yf.Ticker(ticker).info or {}
        q = (info.get('quoteType') or "").upper()
        if q in ["EQUITY", "STOCK"]:
            return "EQUITY"
        if q == "ETF":
            return "ETF"
        if q == "INDEX":
            return "INDEX"
        if q in ["CURRENCY", "CURRENCYPAIR"]:
            return "CURRENCY"
        if q in ["CRYPTOCURRENCY", "CRYPTO"]:
            return "CRYPTOCURRENCY"
        if q in ["FUTURE", "COMMODITY"]:
            return "COMMODITY"
        if info.get("isEtf"):
            return "ETF"
    except Exception:
        pass
    return "UNKNOWN"

def detect_sector(ticker, asset_class):
    if asset_class == "INDEX":
        return "Index"
    if asset_class == "COMMODITY":
        return "Commodities"
    if asset_class == "CRYPTOCURRENCY":
        return "Digital Assets"
    if asset_class == "CURRENCY":
        return "Forex"

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}

    sector = info.get("sector") or info.get("industry") or info.get("category")
    if sector and isinstance(sector, str) and sector.strip():
        return sector.strip()

    summary = (info.get("longBusinessSummary") or info.get("shortName") or "").lower()
    keyword_map = {
        "Technology": ["technology", "software", "semi", "chip", "cloud", "ai"],
        "Financials": ["bank", "financ", "insur", "asset"],
        "Energy": ["oil", "gas", "energy", "pipeline"],
        "Healthcare": ["health", "biotech", "pharm", "medical"],
        "Consumer Discretionary": ["retail", "automotive", "hotel", "leisure"],
        "Consumer Staples": ["food", "beverage", "grocery"],
        "Industrials": ["industrial", "machinery", "aerospace", "logistic"],
        "Utilities": ["utility", "electric", "water"],
        "Real Estate": ["real estate", "reit"],
        "Materials": ["metal", "mining", "chemical"],
        "Communication Services": ["telecom", "communication", "media"]
    }
    for name, terms in keyword_map.items():
        if any(t in summary for t in terms):
            return name
    return "Unknown"

# -----------------------------
# Data retrieval (multi-timeframe aware)
# -----------------------------
def get_history(ticker, timeframe='1d', days=HIST_DAYS):
    """
    timeframe: '1d', '4h', '1h'
    returns a DataFrame for the requested timeframe
    """
    t = yf.Ticker(ticker)
    # Map timeframe to yfinance interval & period
    if timeframe == '1d':
        interval = '1d'
        period = f"{days}d"
    elif timeframe == '4h':
        # yfinance accepts '4h' interval; if it fails fallback to '60m' then aggregate
        interval = '4h'
        period = "120d"   # 4h data limited historically; keep safe window
    elif timeframe == '1h':
        interval = '1h'
        period = "60d"
    else:
        interval = timeframe
        period = f"{days}d"
    try:
        hist = t.history(period=period, interval=interval, actions=False)
        if (hist is None or hist.empty) and interval == '4h':
            # fallback to 60m and downsample to 4h
            hist = t.history(period=period, interval='60m', actions=False)
            if hist is not None and not hist.empty:
                hist = hist.resample('4H').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        if hist is None or hist.empty:
            # try shorter period
            hist = t.history(period="30d", interval=interval, actions=False)
        if hist is None or hist.empty:
            raise ValueError(f"No history for {ticker} {timeframe}")
        return hist.dropna(subset=['Close'])
    except Exception as e:
        # Bubble up a clear error
        raise

# -----------------------------
# Technical & options metrics per timeframe
# -----------------------------
def compute_technical_metrics_from_hist(hist):
    close = hist['Close']
    low = hist['Low'] if 'Low' in hist.columns else close
    vol = hist['Volume'] if 'Volume' in hist.columns else pd.Series([0]*len(hist), index=hist.index)

    tech = {}
    tech['last_close'] = float(close.iloc[-1])
    tech['ema_fast'] = float(ema(close, EMA_FAST).iloc[-1])
    tech['ema_slow'] = float(ema(close, EMA_SLOW).iloc[-1])
    tech['ema_cross'] = int(tech['ema_fast'] > tech['ema_slow'])
    tech['price_above_ema_slow'] = int(close.iloc[-1] > tech['ema_slow'])

    r = rsi(close, RSI_PERIOD)
    tech['rsi'] = float(r.iloc[-1]) if not r.isna().all() else np.nan
    tech['rsi_rising'] = int(r.iloc[-1] > r.iloc[-3]) if len(r) >= 3 else 0

    try:
        lows = low.dropna().iloc[-5:]
        tech['higher_lows_3'] = int(len(lows) >= 3 and lows.iloc[-1] > lows.iloc[-2] > lows.iloc[-3])
    except Exception:
        tech['higher_lows_3'] = 0

    obv = compute_obv(hist)
    tech['obv_latest'] = float(obv.iloc[-1])
    if len(obv) >= OBV_LOOKBACK:
        y = obv.iloc[-OBV_LOOKBACK:].values
        x = np.arange(len(y))
        if np.all(np.isfinite(y)):
            m = np.polyfit(x, y, 1)[0]
            tech['obv_slope'] = float(m)
            tech['obv_slope_pos'] = int(m > 0)
        else:
            tech['obv_slope'] = 0.0
            tech['obv_slope_pos'] = 0
    else:
        tech['obv_slope'] = 0.0
        tech['obv_slope_pos'] = 0

    avg30 = vol.rolling(30, min_periods=5).mean().iloc[-1] if len(vol) >= 5 else (vol.mean() if len(vol)>0 else 0)
    tech['avg_vol_30'] = float(avg30 if not np.isnan(avg30) else 0.0)
    tech['today_vol'] = float(vol.iloc[-1]) if len(vol)>0 else 0.0
    today_up = int(close.iloc[-1] > close.iloc[-2]) if len(close) >= 2 else 0
    tech['vol_spike_up'] = int((tech['today_vol'] > VOLUME_SPIKE_MULT * tech['avg_vol_30']) and today_up)

    return tech

def compute_options_metrics(ticker):
    t = yf.Ticker(ticker)
    res = {
        'opt_nearest_expiry': None,
        'call_vol_sum': np.nan,
        'put_vol_sum': np.nan,
        'call_oi_sum': np.nan,
        'put_oi_sum': np.nan,
        'call_put_vol_ratio': np.nan,
        'call_put_oi_ratio': np.nan
    }
    try:
        exps = t.options
        if not exps:
            return res
        ne = exps[0]
        chain = t.option_chain(ne)
        calls = chain.calls
        puts = chain.puts
        cv = int(calls['volume'].dropna().sum()) if not calls.empty else 0
        pv = int(puts['volume'].dropna().sum()) if not puts.empty else 0
        coi = int(calls['openInterest'].dropna().sum()) if not calls.empty else 0
        poi = int(puts['openInterest'].dropna().sum()) if not puts.empty else 0
        res.update({
            'opt_nearest_expiry': ne,
            'call_vol_sum': cv,
            'put_vol_sum': pv,
            'call_oi_sum': coi,
            'put_oi_sum': poi,
            'call_put_vol_ratio': safe_div(cv,pv),
            'call_put_oi_ratio': safe_div(coi,poi)
        })
    except Exception:
        pass
    return res

# -----------------------------
# Scoring functions (price, flow, fundamentals)
# -----------------------------
def score_price_momentum_from_tech(tech):
    # returns 0..100
    w_ema = 0.35
    w_price = 0.25
    w_rsi = 0.20
    w_hl = 0.20
    score = 0.0
    score += w_ema * (1.0 if tech.get('ema_cross',0)==1 else 0.0)
    score += w_price * (1.0 if tech.get('price_above_ema_slow',0)==1 else 0.0)
    r = tech.get('rsi', np.nan)
    if np.isfinite(r):
        if r < 30: r_score = 0.0
        elif r > 80: r_score = 0.2
        else: r_score = max(0.0, 1.0 - abs(r-60)/30.0)
        if tech.get('rsi_rising',0): r_score = min(1.0, r_score*1.2)
    else:
        r_score = 0.5
    score += w_rsi * r_score
    score += w_hl * (1.0 if tech.get('higher_lows_3',0)==1 else 0.0)
    return float(score*100.0)

def score_volume_flow_from_tech_opt(tech, opt, asset_class):
    # returns 0..100
    w_vol_spike = 0.30
    w_obv = 0.30
    w_cp_vol = 0.20
    w_cp_oi = 0.20
    s = 0.0
    s += w_vol_spike * (1.0 if tech.get('vol_spike_up',0)==1 else 0.0)
    s += w_obv * (1.0 if tech.get('obv_slope_pos',0)==1 else 0.0)
    cpv = opt.get('call_put_vol_ratio', np.nan)
    cpoi = opt.get('call_put_oi_ratio', np.nan)
    if asset_class in ["INDEX","CURRENCY","COMMODITY","CRYPTOCURRENCY"]:
        s += w_cp_vol * 0.5
        s += w_cp_oi * 0.5
    else:
        if np.isfinite(cpv):
            mapped = max(0.0, min(1.0, cpv/2.0))
            s += w_cp_vol * mapped
        else:
            s += w_cp_vol * 0.5
        if np.isfinite(cpoi):
            mapped = max(0.0, min(1.0, cpoi/2.0))
            s += w_cp_oi * mapped
        else:
            s += w_cp_oi * 0.5
    total = w_vol_spike + w_obv + w_cp_vol + w_cp_oi
    return float(s/total*100.0)

def score_fundamentals(ticker):
    t = yf.Ticker(ticker)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}
    earnings_score = 0.5
    try:
        qearn = t.quarterly_earnings
        if qearn is not None and 'Earnings' in qearn.columns:
            vals = qearn['Earnings'].dropna()
            if len(vals) >= 2:
                last, prev = vals.iloc[-1], vals.iloc[-2]
                if prev != 0:
                    g = (last - prev)/abs(prev)
                    earnings_score = max(0.0, min(1.0, (g+1)/2.0))
    except Exception:
        pass
    short_ratio = info.get('shortRatio', np.nan)
    short_score = 0.5
    if np.isfinite(short_ratio):
        short_score = max(0.0, min(1.0, 1.0 - (short_ratio - 0.05)/0.25))
    rec = info.get('recommendationMean', np.nan)
    rec_score = 0.5
    if np.isfinite(rec):
        rec_score = max(0.0, min(1.0, (5.0 - rec)/4.0))
    raw = 0.5*earnings_score + 0.3*rec_score + 0.2*short_score
    return float(max(0.0, min(1.0, raw))*100.0)

# -----------------------------
# Institutional flow proxy
# -----------------------------
def institutional_flow_proxy(tech, opt):
    cpv = opt.get('call_put_vol_ratio', np.nan)
    cpv_score = max(0.0, min(1.0, cpv/2.0)) if np.isfinite(cpv) else 0.5
    avg30 = tech.get('avg_vol_30', 0.0)
    today = tech.get('today_vol', 0.0)
    if avg30 and avg30 > 0:
        mult = today/avg30
        vol_score = max(0.0, min(1.0, (mult-1.0)/2.0 + 0.5))
    else:
        vol_score = 0.5
    obv_pos = 1.0 if tech.get('obv_slope_pos', 0) == 1 else 0.0
    w_opts, w_vol, w_obv = 0.4, 0.4, 0.2
    raw = w_opts*cpv_score + w_vol*vol_score + w_obv*obv_pos
    return float(raw*100.0)

# -----------------------------
# Buy signal helpers: threshold & history
# -----------------------------
def get_buy_signal_from_score(score):
    if score >= 80:
        return "STRONG BUY"
    elif score >= 75:
        return "BUY"
    elif score >= 65:
        return "WATCHLIST"
    else:
        return "NO TRADE"

def append_history_row(ticker, score, signal, history_file=HISTORY_CSV):
    row = pd.DataFrame([{
        "Datetime": datetime.utcnow().isoformat(),
        "Ticker": ticker,
        "Score": score,
        "Signal": signal
    }])
    header = not os.path.exists(history_file)
    row.to_csv(history_file, mode='a', header=header, index=False)

def get_score_trend(ticker, history_file=HISTORY_CSV, lookback=3):
    if not os.path.exists(history_file):
        return "N/A"
    try:
        df = pd.read_csv(history_file)
        df_t = df[df["Ticker"]==ticker].tail(lookback)
        if len(df_t) < 2:
            return "N/A"
        prev_mean = df_t["Score"].iloc[:-1].mean() if len(df_t) > 1 else df_t["Score"].iloc[0]
        last = df_t["Score"].iloc[-1]
        if last > prev_mean:
            return "RISING"
        elif last < prev_mean:
            return "FALLING"
        else:
            return "FLAT"
    except Exception:
        return "N/A"

# -----------------------------
# Multi-timeframe confirmation & Buy-The-Dip
# -----------------------------
def compute_mtf_confirmation(ticker):
    """
    Returns:
      mtf_positive_count: int
      mtf_confirm: bool (>=MTF_CONFIRM_THRESHOLD)
      mtf_details: dict of timeframe -> price_score
    """
    positives = 0
    details = {}
    for tf in MTF_TIMEFRAMES:
        try:
            hist = get_history(ticker, timeframe=tf)
            tech = compute_technical_metrics_from_hist(hist)
            price_score = score_price_momentum_from_tech(tech)
            details[tf] = price_score
            if price_score >= MTF_POSITIVE_PRICE_SCORE:
                positives += 1
        except Exception:
            # treat missing timeframe as neutral (not positive)
            details[tf] = np.nan
    confirmed = positives >= MTF_CONFIRM_THRESHOLD
    return positives, confirmed, details

def detect_buy_the_dip(ticker):
    """
    Detects BTD:
     - daily uptrend (price above EMA50 & ema_cross) if required
     - recent pullback from N-day high between BTD_MIN_PULLBACK and BTD_MAX_PULLBACK
    """
    try:
        hist = get_history(ticker, timeframe='1d')
    except Exception:
        return False, np.nan, np.nan
    tech = compute_technical_metrics_from_hist(hist)
    last_close = tech.get('last_close')
    # check daily uptrend condition
    if BTD_REQUIRE_DAILY_UPTREND:
        if not (tech.get('ema_cross',0) == 1 and tech.get('price_above_ema_slow',0) == 1):
            return False, None, None
    # compute recent high
    look = hist['Close'].iloc[-BTD_LOOKBACK_DAYS:] if len(hist) >= BTD_LOOKBACK_DAYS else hist['Close']
    recent_high = float(look.max())
    pullback = (recent_high - last_close) / recent_high if recent_high>0 else 0.0
    is_btd = (pullback >= BTD_MIN_PULLBACK) and (pullback <= BTD_MAX_PULLBACK)
    return bool(is_btd), round(pullback, 4), recent_high

# -----------------------------
# Full analysis per ticker
# -----------------------------
def analyze_ticker(ticker):
    rec = {'ticker': ticker}
    try:
        asset_class = detect_asset_class(ticker)
        rec['asset_class'] = asset_class
        rec['sector'] = detect_sector(ticker, asset_class)

        # Daily technical & options
        hist_daily = get_history(ticker, timeframe='1d')
        tech_daily = compute_technical_metrics_from_hist(hist_daily)
        opt = compute_options_metrics(ticker)

        # Subscores
        price_sub = score_price_momentum_from_tech(tech_daily)
        flow_sub = score_volume_flow_from_tech_opt(tech_daily, opt, asset_class)
        fund_sub = np.nan
        if SCORES_CONFIG.get(asset_class, SCORES_CONFIG['UNKNOWN'])['fund'] > 0:
            try:
                fund_sub = score_fundamentals(ticker)
            except Exception:
                fund_sub = np.nan

        # Institutional proxy
        inst_proxy = institutional_flow_proxy(tech_daily, opt) if INST_FLOW_WEIGHT > 0 else np.nan

        # Compute combined weights including INST_FLOW_WEIGHT
        base_cfg = SCORES_CONFIG.get(asset_class, SCORES_CONFIG['UNKNOWN'])
        base_price = base_cfg['price']
        base_flow = base_cfg['flow']
        base_fund = base_cfg['fund']
        base_total = base_price + base_flow + base_fund
        inst_w = INST_FLOW_WEIGHT
        remaining = max(0.0, 1.0 - inst_w)
        if base_total > 0:
            p_w = (base_price / base_total) * remaining
            f_w = (base_flow / base_total) * remaining
            fund_w = (base_fund / base_total) * remaining
        else:
            p_w = remaining*0.6; f_w = remaining*0.4; fund_w = 0.0

        fund_val = fund_sub if not (fund_sub is None or np.isnan(fund_sub)) else 50.0
        inst_val = inst_proxy if not (inst_proxy is None or np.isnan(inst_proxy)) else 50.0

        final_score = p_w*price_sub + f_w*flow_sub + fund_w*fund_val + inst_w*inst_val

        # MTF confirmation
        mtf_count, mtf_confirm, mtf_details = compute_mtf_confirmation(ticker)

        # Buy-the-dip
        btd_flag, btd_pullback, btd_recent_high = detect_buy_the_dip(ticker)

        # Buy signal basic
        buy_signal = get_buy_signal_from_score(final_score)
        # Now refine with MTF and BTD:
        # - Require MTF confirmation for a normal BUY/STRONG BUY
        # - If BTD true and score >= 70, allow BUY even if MTF missing (configurable)
        if buy_signal in ("STRONG BUY","BUY"):
            if not mtf_confirm:
                # if it's a strong buy but no MTF confirmation, downgrade to WATCHLIST unless BTD allows buy
                if buy_signal == "STRONG BUY":
                    # keep as STRONG BUY only if mtf_confirm True
                    if not mtf_confirm:
                        if btd_flag and final_score >= 70:
                            buy_signal = "BUY (BTD)"
                        else:
                            buy_signal = "WATCHLIST"
                else:  # BUY
                    if btd_flag and final_score >= 70:
                        buy_signal = "BUY (BTD)"
                    else:
                        buy_signal = "WATCHLIST"
        else:
            # If NO TRADE but BTD + MTF confirms, allow WATCHLIST or BUY if score decent
            if btd_flag and (final_score >= 70):
                buy_signal = "BUY (BTD)"
            elif btd_flag and (final_score >= 65):
                buy_signal = "WATCHLIST (BTD)"

        # Score trend from history
        score_trend = get_score_trend(ticker)

        # Append history
        append_history_row(ticker, final_score, buy_signal)

        # Fill record
        rec.update({
            'price_subscore': round(price_sub,2),
            'flow_subscore': round(flow_sub,2),
            'fund_subscore': round(fund_val,2),
            'inst_flow_proxy': round(inst_val,2),
            'final_readiness_score': round(final_score,2),
            'buy_signal': buy_signal,
            'signal_strength': "High" if final_score>=80 else ("Medium" if final_score>=75 else ("Low" if final_score>=65 else "None")),
            'score_trend': score_trend,
            'mtf_positive_count': mtf_count,
            'mtf_confirm': bool(mtf_confirm),
            'mtf_details': mtf_details,
            'buy_the_dip': bool(btd_flag),
            'btd_pullback_pct': btd_pullback,
            'btd_recent_high': btd_recent_high,
            'last_close': tech_daily.get('last_close'),
            'avg_vol_30': tech_daily.get('avg_vol_30'),
            'opt_nearest_expiry': opt.get('opt_nearest_expiry'),
            'call_put_vol_ratio': opt.get('call_put_vol_ratio'),
        })

    except Exception as e:
        rec['error'] = str(e)
    return rec

# -----------------------------
# Bulk lists (Wikipedia fetchers)
# -----------------------------
def fetch_sp500_tickers():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        r = requests.get(url, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table", {"id": "constituents"})
        df = pd.read_html(str(table))[0]
        tickers = [t.replace('.', '-') for t in df['Symbol'].tolist()]
        return tickers
    except Exception:
        return ["AAPL","MSFT","AMZN","GOOGL","META"]

def fetch_dow30_tickers():
    return ["AAPL","AMGN","AXP","BA","CAT","CRM","CSCO","CVX","DIS","DOW","GS","HD","HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","PG","TRV","UNH","V","VZ","WBA","WMT"]

def fetch_nasdaq100_tickers():
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    try:
        r = requests.get(url, timeout=12)
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table", {"class": "wikitable sortable"})
        df = pd.read_html(str(table))[0]
        tickers = [t.replace('.', '-') for t in df['Ticker'].tolist()]
        return tickers
    except Exception:
        return ["AAPL","MSFT","NVDA","TSLA","AMZN","META","GOOGL","PEP","AVGO","ADBE"]

# -----------------------------
# Runner & Excel writer
# -----------------------------
def run_and_save(tickers, output_file=OUTPUT_FILE):
    rows = []
    for t in tickers:
        print("Analyzing:", t)
        r = analyze_ticker(t)
        rows.append(r)

    df = pd.json_normalize(rows)
    if 'final_readiness_score' in df.columns:
        df_sorted = df.sort_values('final_readiness_score', ascending=False)
    else:
        df_sorted = df

    # Write Excel with sheets
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df_sorted.to_excel(writer, sheet_name="ALL_ASSETS_RANKED", index=False)

        if 'asset_class' in df_sorted.columns:
            for cls in df_sorted['asset_class'].dropna().unique():
                sub = df_sorted[df_sorted['asset_class'] == cls].sort_values('final_readiness_score', ascending=False)
                if not sub.empty:
                    sheet = f"Category_{cls}"[:31]
                    sub.to_excel(writer, sheet_name=sheet, index=False)

        if 'sector' in df_sorted.columns:
            df_sorted.sort_values(['sector','final_readiness_score'], ascending=[True, False]).to_excel(writer, sheet_name='BY_SECTOR', index=False)
            for s in df_sorted['sector'].dropna().unique():
                subset = df_sorted[df_sorted['sector']==s].sort_values('final_readiness_score', ascending=False)
                if not subset.empty:
                    sheet = f"SECTOR_{str(s)[:25]}"
                    try:
                        subset.to_excel(writer, sheet_name=sheet[:31], index=False)
                    except Exception:
                        pass

        if 'sector' in df_sorted.columns and 'final_readiness_score' in df_sorted.columns:
            summary = df_sorted.groupby('sector')['final_readiness_score'].agg(['mean','count']).reset_index()
            summary = summary.rename(columns={'mean':'avg_readiness_score','count':'count'})
            summary.to_excel(writer, sheet_name='SECTOR_SUMMARY', index=False)

        # Optional groups (SP500/DOW/NAS100) if tickers present
        try:
            sp500 = fetch_sp500_tickers()
        except Exception:
            sp500 = []
        groups = {
            "SP500": [t for t in sp500 if t in df_sorted['ticker'].values] if sp500 else [],
            "DOW30": [t for t in fetch_dow30_tickers() if t in df_sorted['ticker'].values],
            "NAS100": [t for t in fetch_nasdaq100_tickers() if t in df_sorted['ticker'].values]
        }
        for gname, tlist in groups.items():
            if tlist:
                gdf = df_sorted[df_sorted['ticker'].isin(tlist)].sort_values('final_readiness_score', ascending=False)
                if not gdf.empty:
                    try:
                        gdf.to_excel(writer, sheet_name=gname[:31], index=False)
                    except Exception:
                        pass

    print("Saved Excel ->", output_file)
    return df_sorted

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    # Build universe - you can uncomment fetch_sp500_tickers() if you want to scan the full S&P 500 (slow)
    tickers = list(dict.fromkeys(TOP_LEVEL_TICKERS))
    # Example to extend with full indices:
    # sp500_all = fetch_sp500_tickers()
    # tickers = list(dict.fromkeys(tickers + sp500_all))

    df = run_and_save(tickers, OUTPUT_FILE)
    if 'final_readiness_score' in df.columns:
        print("\nTop 20 by readiness:")
        cols = ['ticker','asset_class','sector','final_readiness_score','buy_signal','mtf_confirm','buy_the_dip']
        print(df[cols].head(20).to_string(index=False))
    else:
        print("No scores computed.")
