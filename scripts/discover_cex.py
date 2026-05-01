"""
Discover known/labeled addresses among top NOT holders via tonapi.io,
classify into cex / protocol / named, and emit a JS LABELS map.

Output:
  C:\\Users\\livea\\duflat\\exchanges.json   — { addr: {name, kind, is_scam} }
  C:\\Users\\livea\\duflat\\exchanges.js     — `const LABELS = {...};` snippet

Usage: python discover_cex.py [TOP_N=9000]   # 9000 = tonapi.io holders cap
"""
import urllib.request, urllib.error, json, base64, os, sys, time

JETTON   = "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".tonapi_key")
OUT_JSON = r"C:\Users\livea\duflat\exchanges.json"
OUT_JS   = r"C:\Users\livea\duflat\exchanges.js"
PAGE     = 1000   # tonapi holders page size cap
BULK     = 100    # accounts/_bulk cap

CEX_KEYWORDS = [
    "binance", "okx", "bybit", "mexc", "gate.io", "gateio", "bitget",
    "kucoin", "htx", "huobi", "bitrue", "coinspot", "lbank", "rapira",
    "ompfinex", "bitkub", "coinbase", "kraken", "telegram wallet",
    "wallet in telegram", "bitfinex", "crypto.com", "bitmart", "bitstamp",
    "bingx", "whitebit", "phemex", "poloniex", "fragment market",
    "paribu", "btcturk", "btc-turk", "binance tr", "garantex", "exmo",
    "farhad exchange", "exchange", "exch.io", "cwallet",
    "bitvavo", "upbit", "bithumb", "korbit", "bitflyer", "indodax",
    "max maicoin", "ascendex", "deepcoin",
]
PROTOCOL_KEYWORDS = [
    "ston.fi", "dedust", "voucher swap", "minter", "vault", "elector",
    "tonstakers", "evaa", "storm", "megaton", "notcoin", "fragment",
    "tonkeeper battery", "tonhub", "tonco", "ton diamonds",
    "ton foundation",
]

# Manual overrides — wins over tonapi.io's name + auto-classification.
# Use for cases where on-chain flow analysis reveals the true owner
# (e.g. CEX consolidation wallets that ops staff renamed to junk .ton domains).
MANUAL_OVERRIDES = {
    # Binance deposit/consolidation wallet (was labeled "selling-domain-dogs.ton"):
    # 100% outflow to Binance Hot, 70% inflow from Binance Hot, 42M TON balance.
    "UQD4uGNdB4a3f52mYOZf0x1nCmdd1DAvrLppL0a1cetTYCQx":
        {"name": "Binance Deposit", "kind": "cex"},
    # Second Binance hot wallet — tonapi already names it "Binance Hot Wallet"
    # but it wasn't in our top-9000 NOT holders so the discovery missed it.
    "UQCOkbUDgcNt1CrM21H1y12WhIVotJJPgHmxpa5-EPQ-2iNl":
        {"name": "Binance Hot Wallet 2", "kind": "cex"},

    # ---- 2026-05-01 batch: top-100 unlabeled holders, NOT-flow analysis ----
    # All entries below: tonapi has no name; flow shows >=85% inflow from a
    # single CEX family with ~zero outflow (sub/cold pattern) — or both sides
    # >=85% same family (internal). Source: scripts/batch_flow_report.json.
    # rank#10, in:97.0% OKX, out~0, ev=10, bal=1438M NOT
    "UQB_LPN1koEFYocWeuKaAkDTQMFFycDs9CGrwPLpnJQ0U6Gy":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#15, in:85.8%/out:99.5% OKX, ev=45, bal=1172M NOT
    "UQCkdi_s8DUFA1kjX5jrr7oLG0SbVTGK4-Q52Yvdw1cRGfku":
        {"name": "OKX Internal", "kind": "cex"},
    # rank#18, in:85.7% OKX, out~0, ev=7, bal=994M NOT
    "UQBmlAmSmKc6GbesAPi3Pk6i-ooyUPXgFS2LmLv0uTXqP-ei":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#24, in:100.0% Binance, out~0, ev=3, bal=696M NOT
    "UQDYM0YvFy2-1J4vTsn_GKUx8UKBCvs2A5QKJt8wVTXqhsK0":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#25, in:100.0%/out:100.0% OKX, ev=499, bal=644M NOT
    "UQDY4-KtVxawZU_Vva7KTOhlhx8Ho0jI0ahyebYT5YuJkYSf":
        {"name": "OKX Internal", "kind": "cex"},
    # rank#27, in:100.0% Binance, out~0, ev=130, bal=610M NOT
    "UQCiErgR_u2U30EI2G5RzLfLANOhzOz8jXU5K2bkVOtczTcP":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#28, in:100.0% Binance, out~0, ev=17, bal=598M NOT
    "UQAPykgBUhbI2Fz_JNhT89NhT8HTKSw3Im32EipXtqLSIkmt":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#44, in:87.4% OKX, out~0, ev=8, bal=201M NOT
    "UQCgJMAdLq3CtecfGqKY3bJye9kjrDp6BW_MnW_7zwclJQKz":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#50, in:100.0% lbank.info, out~0, ev=3, bal=151M NOT
    "UQDg5iDIqj8O4xHM0rsL26Vo_a4OKZnblc_EI6LJ37kRC1AC":
        {"name": "lbank.info Cold", "kind": "cex"},
    # rank#56, in:100.0% Binance, out~0, ev=2, bal=122M NOT
    "UQDQKawuKNAAC6NJuiBsnyr8ewqCLuFmYWavUoP7BIVxAmVC":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#57, in:100.0% Binance, out~0, ev=2, bal=120M NOT
    "UQDmTo2Aun0l40gEng6BiidXALpwEdAOdxNzHOGYQ3p5x5Sj":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#74, in:100.0% Binance, out~0, ev=2, bal=80M NOT
    "UQCJGVn5fz2lGruG3QUfKhU07MvKHEhxQhzheiyvSFlraxwP":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#78, in:100.0% Bitget, out~0, ev=22, bal=71M NOT
    "UQDNVsqiDSHhUKPCp6tf0kRXvYpGkXaKmNtXKJ5nxiUPqRD0":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#80, in:87.4% Binance, out~0, ev=26, bal=68M NOT
    "UQDEYl2dmHSU2pvoSE8CS-PwkjGNcrq3A6v-B7X6Ly44OcE1":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#83, in:100.0% Binance, out~0, ev=2, bal=63M NOT
    "UQCEfvjUxopnkTkFfAR9LEvQhwEm_1CEOTUWausV2BfnTcUy":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#88, in:100.0% Binance, out~0, ev=3, bal=58M NOT
    "UQArhe9wZz4NYlLdaJHJHX70fxUKhUlmAP2t1nSGcf2k3Sw3":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#92, in:100.0% OKX, out~0, ev=3, bal=56M NOT
    "UQAD8XEJQppmZDZvlTAKopt2E_c-Xbhzt7_vKH98W4qB5HOs":
        {"name": "OKX Cold", "kind": "cex"},

    # ---- 2026-05-01 batch #2: top 100-1000 unlabeled holders, NOT-flow analysis ----
    # Same heuristic as the prior batch: >=80% inflow OR outflow from a single CEX family.
    # Source: scripts/batch_flow_report_top1000.json.
    # rank#104, in:96.6%[Binance]/out:0%[-], ev=13, bal=44.2M
    "UQCpj_o0KHiwPbf82pPQWKGSP0MbDhCx7IBI-gH_Pb5T2UiO":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#108, in:100.0%[Binance]/out:0%[-], ev=127, bal=41.5M
    "UQBSxsL86qU_FRQMfJq8vRJtBG_X9W2lTL1M1KfTbEX1rR-_":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#109, in:100.0%[OKX]/out:0%[-], ev=7, bal=41.0M
    "UQCJyUqClMkFAnuKPybjFOgHqUQ0fbG45Fi33PtHaNfe1czc":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#113, in:100.0%[MEXC]/out:0%[-], ev=1, bal=38.2M
    "UQDOOTbcADshrW_QyUezIPKqCzdWJG8MsM6OgfFL255IshXK":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#147, in:1.9%[OKX]/out:100.0%[OKX], ev=61, bal=30.5M
    "UQBXzIZ5k-1jQlGR7hGGOMpIJIbrE8XQieWesPHymfoxa8kL":
        {"name": "OKX Deposit", "kind": "cex"},
    # rank#152, in:100.0%[MEXC]/out:0%[-], ev=11, bal=28.3M
    "UQB9MC2viPZ1_jaNGbkOPVV57R6mJ5ovBKM1aNeRYN6G5V2o":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#155, in:100.0%[Binance]/out:0%[-], ev=1, bal=28.0M
    "UQDRONjMI_1wgqAL-h6hdMazQTyTKqnLhRvZz6V0KdUa4rlm":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#162, in:100.0%[OKX]/out:0%[-], ev=2, bal=26.4M
    "UQDNlMHUDcsLjBjaWeoEB6bH8WDwLtavvwlLsiC_-Y2ekeqb":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#164, in:100.0%[lbank.info]/out:0%[-], ev=2, bal=26.1M
    "UQBkwJ_CWNHCY0KUxfVXdGeyF_i2oVXWvXVaAHstNdf6aelE":
        {"name": "lbank.info Cold", "kind": "cex"},
    # rank#172, in:100.0%[lbank.info]/out:0%[-], ev=1, bal=24.0M
    "UQBr4lIb0Ne2V2fx01OI4jCc8oSNVdXYQ0Y5-11sL7IyWYbt":
        {"name": "lbank.info Cold", "kind": "cex"},
    # rank#177, in:100.0%[Binance]/out:0%[-], ev=2, bal=23.0M
    "UQASniao-4aP3WXvEJKNjbYGgZ8qy2UFEheGOMfhsmCnKhco":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#184, in:100.0%[Binance]/out:0%[-], ev=3, bal=21.0M
    "UQDB0TLpGbHx0vrNYKchMyBihCxfCIU6eaazVJbCTooJ2TeZ":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#185, in:100.0%[Binance]/out:0%[-], ev=6, bal=20.7M
    "UQCEqa5GKxOJPr3C1N1WhZwuukcV-D2JF_Q5QjhffK9GlRa4":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#192, in:100.0%[Binance]/out:0%[-], ev=3, bal=20.0M
    "UQCsG02jBNCStgL5HyDGkEBCJq-F2T-M-UJVCfw_CX_-oXuT":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#200, in:0%[-]/out:100.0%[Gate.io], ev=7, bal=19.7M
    "UQBi3f2ADbsbzeVwa-uKPii7jIttaIplToltgSflzRMgq55A":
        {"name": "Gate.io Deposit", "kind": "cex"},
    # rank#210, in:100.0%[MEXC]/out:0%[-], ev=10, bal=18.1M
    "UQAa7ZkFEabP0rTuAYa2Kr-VMOYoDu7q7FS8QxrRSfwGKqe3":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#217, in:100.0%[MEXC]/out:0%[-], ev=3, bal=17.1M
    "UQBQDVjD2ZvskPfrg9DJO3OwiJBx7XdneZU6nCflpgDXtypN":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#221, in:100.0%[MEXC]/out:0%[-], ev=2, bal=16.8M
    "UQATp74958DsWobRhq7yd8FMLDDSQd0gz8bSJMtWGKFtDrKb":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#224, in:100.0%[Binance]/out:0%[-], ev=5, bal=16.4M
    "UQDaI9wRrhNBF__ujvldXTOm8Ng7QQ2olxJ00Bw3g-HXiZop":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#231, in:89.2%[MEXC]/out:0%[-], ev=43, bal=15.7M
    "UQBZPxNyPLpmObaGwfZFaEGj-0d91nJQjxrAISL4T6pB1xVM":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#233, in:100.0%[Bitget]/out:0%[-], ev=1, bal=15.3M
    "UQAH-GM9B1_XL0Skdnvc91isz3_A30bGmDmhbgLN4PHvIgE0":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#236, in:100.0%[MEXC]/out:0%[-], ev=4, bal=15.1M
    "UQDtY3oAD9x6JWaVIux4LKf1mP-2x9nvw22uIfKU7usscAYC":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#241, in:100.0%[Binance]/out:0%[-], ev=2, bal=14.8M
    "UQAORqYGkAA70EPvF7WNSZMG7d8jECYKVzBCxi9tYqrxSoy3":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#248, in:100.0%[Binance]/out:0%[-], ev=1, bal=14.5M
    "UQApjN7PK6UknElx7xT6iM6GyYs1QSVlXf2_I21fp6_JckC2":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#250, in:100.0%[Binance]/out:0%[-], ev=2, bal=14.0M
    "UQD4nQbv0IOllXsREBDmXklmmf8ZqI-vDJpcpFPtcohw-BMK":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#253, in:100.0%[OKX]/out:90.2%[OKX], ev=200, bal=13.7M
    "UQALPBuydPH5HhVljyMfJ0T_7jR1VrE5kmNxFifTJtQ2fWM4":
        {"name": "OKX Internal", "kind": "cex"},
    # rank#256, in:100.0%[Binance]/out:0%[-], ev=7, bal=13.5M
    "UQCmg4J3A5bvLB9pcEsCZh9YcF8GcCkxDlceQLsQKZOlEK-P":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#257, in:100.0%[OKX]/out:0%[-], ev=6, bal=13.4M
    "UQDW_77lq04_KBMfYP9DCvm3yo0LPJAgciFraEPOq22dIUmS":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#260, in:99.5%[OKX]/out:0%[-], ev=3, bal=13.2M
    "UQAFkoVS5SoolPy25NLDHABHczXfiD4TntiaJbY_H63cUSOY":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#271, in:100.0%[Binance]/out:0%[-], ev=1, bal=12.6M
    "UQDvEFxgqpnZ5eOPvyIj9gMhkOQUqzwyemuuXoitwIJ2xISW":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#272, in:100.0%[MEXC]/out:0%[-], ev=8, bal=12.6M
    "UQBQgG0PXsEjRWOY-tk6-wxfBB0UDadQ5U2eFl7eKg4aUYcB":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#274, in:100.0%[MEXC]/out:0%[-], ev=2, bal=12.5M
    "UQCwqpqU_uFK2AllRfNFUOl2pcxx8M-ZfMpCUo40OFsKjPtm":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#276, in:96.8%[Binance]/out:0%[-], ev=5, bal=12.5M
    "UQBUDAYhWh_sP8ApLdcXjchmVDGdnMJ0aRsxSYhcabOKTIJn":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#277, in:96.0%[Binance]/out:0%[-], ev=16, bal=12.5M
    "UQB-6BxOjpB-nTJDbYw_FX6nx4xdN5vSL6yJknFBf7MaiA85":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#286, in:100.0%[Binance]/out:0%[-], ev=57, bal=12.1M
    "UQAKBsfqTzb08Ou2qNGFq1NwGrS5MXUOVF4aK29rbf1GU3xh":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#287, in:100.0%[Binance]/out:0%[-], ev=114, bal=12.1M
    "UQC59FxwLBbPzSiGghIwwO3IuWOmK1Qu1isGJyR53gBj4sdL":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#291, in:100.0%[OKX]/out:0%[-], ev=4, bal=12.0M
    "UQD7Xl3NCxscAuTxEg3Nsklsd_yLx32KnQbXkhy9HDcDci2P":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#306, in:94.5%[Binance]/out:0%[-], ev=19, bal=11.4M
    "UQBoIYlQBr3aoPOGKoUgezQsgb5kIBsxRKVxeBHN5EnAPJd3":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#311, in:91.0%[Binance]/out:0%[-], ev=10, bal=11.2M
    "UQCruT0e40zvplVy8Lq91J8aG1d5m9LuvECuflTr5O6niGNG":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#316, in:100.0%[Binance]/out:0%[-], ev=4, bal=11.0M
    "UQAZ9xlA9DHpQ49wuqZqWW07zhXX1mttaLC2nqYPEtcuthr-":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#320, in:85.7%[Bitget]/out:100.0%[OKX], ev=11, bal=10.8M
    "UQAV5Of9JAk8iT233ORrI9MNQ8Ani41FwQsaqdTGCRjIf89d":
        {"name": "OKX Deposit", "kind": "cex"},
    # rank#323, in:99.6%[Bitget]/out:0%[-], ev=6, bal=10.6M
    "UQA_vgoiM-a7O1UEwqTK8fFDwsr2L0Oyyhp0lRam88GLPtBR":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#340, in:100.0%[Bitget]/out:0%[-], ev=1, bal=10.1M
    "UQCNymQ_2Qsqshogklm6PFEh8FuC0FCyJpbaAwdDq4fsjxLH":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#353, in:96.6%[Binance]/out:0%[-], ev=27, bal=10.0M
    "UQDxl2X0MsM7QDc5LWtDnsllS-ph_7OFA-yXQt_oTQmLLp-Q":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#355, in:100.0%[Binance]/out:0%[-], ev=2, bal=10.0M
    "UQAF3LCYM6sOfDe1peWFxPPBlRFhe1-2vJDkspwbFUKQ_4o2":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#363, in:100.0%[OKX]/out:0%[-], ev=4, bal=10.0M
    "UQApROwDA0T-9CSdh7Gdt0I-FcS6aSvIJV-STdxCn1kR9WlJ":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#365, in:100.0%[MEXC]/out:0%[-], ev=41, bal=9.9M
    "UQCPbCEw-1L-wICGscSFrk8tuM4pq65mqyqc0taY7S2Mz5mN":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#370, in:100.0%[Binance]/out:0%[-], ev=3, bal=9.5M
    "UQDFN-T3vTf2Al64VbBz6jq5_7O9kVB_RQD0Vs9cRfHBDs0t":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#371, in:100.0%[Binance]/out:0%[-], ev=2, bal=9.5M
    "UQAV-RZpRCVJfc0VxW5U2aP30MRBOk4sNdla9sE6xfIfYPuw":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#378, in:91.2%[OKX]/out:2.4%[OKX], ev=23, bal=9.1M
    "UQCqbcU-LRjkNxTvwQqVANZXK6OsLNst0PwNUyOFysAkOeGb":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#394, in:80.3%[lbank.info]/out:0%[-], ev=5, bal=8.4M
    "UQBN_hhDd1zCGG6reOI8PAIh6S-8dgVFe85COIprsgAGUqF9":
        {"name": "lbank.info Cold", "kind": "cex"},
    # rank#397, in:100.0%[MEXC]/out:0%[-], ev=2, bal=8.4M
    "UQBFc-46F_4IZIKISp624CjSQP4uasUnfMqF9gYjtNsxiaDZ":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#400, in:100.0%[Bitget]/out:0%[-], ev=5, bal=8.1M
    "UQBgWMlSNsEHeiYp8I6NRXo13tmo1Irr8qO7ZXFAzgdo_iiU":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#404, in:100.0%[Telegram Wallet]/out:0%[-], ev=6, bal=8.0M
    "UQDeQdDO6gRkT0Juab1MExQ7x6BLa3QCf-Rn78NE_kwh0huk":
        {"name": "Telegram Wallet Cold", "kind": "cex"},
    # rank#409, in:100.0%[Binance]/out:0%[-], ev=6, bal=7.8M
    "UQBZmwPiMoDjMsiTxDaCfQcIkAxSbnOHZDpTC9B98VMhIPqp":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#417, in:100.0%[MEXC]/out:0%[-], ev=1, bal=7.5M
    "UQCcgw0-ykW8E1SqsrJleTflQ9kJ5-rKGjLtodLG4-UlTMzy":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#421, in:99.0%[Binance]/out:0%[-], ev=6, bal=7.4M
    "UQCx714BnJuss6SOJsTaCN8tcr27FMtJBFC0hUkZOKkZQXER":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#430, in:100.0%[Binance]/out:0%[-], ev=4, bal=7.2M
    "UQDbldgnITf_aTpqVjVY5kkKo2IEpAWCT4bsDSttS8WTQh49":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#434, in:100.0%[Binance]/out:0%[-], ev=10, bal=7.2M
    "UQAMoZPtm3TCY7a1-Aq3R2JRONlPloJf0fS3L8ZKAUXscfpT":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#442, in:100.0%[MEXC]/out:0%[-], ev=5, bal=7.0M
    "UQBphCthYXb_lETYopWtbSXtwfb7RKJGO9NEuIBPMPDMHozt":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#458, in:81.4%[Bitget]/out:0%[-], ev=6, bal=6.9M
    "UQCkbZz-Wkr61zwroaBbhfu-nx8MCuHSR8eV5UJEOYzwcfDv":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#460, in:99.3%[lbank.info]/out:0%[-], ev=3, bal=6.9M
    "UQAkAddIVaJOo7RlrdA1YFLwUx4rvjkm9wp0UvO3GbzK4toY":
        {"name": "lbank.info Cold", "kind": "cex"},
    # rank#469, in:100.0%[OKX]/out:0%[-], ev=1, bal=6.6M
    "UQDgl_7P1Cmu5j6ePi0LhnXLRWFtudLIEhWvQUHJI9e28T3K":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#475, in:100.0%[Binance]/out:0%[-], ev=2, bal=6.5M
    "UQAeWEaNXSSg_PwNncagDcRK1fBYj3xQy0l7GTlTDDD8kmT8":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#477, in:99.9%[MEXC]/out:0%[-], ev=14, bal=6.5M
    "UQAajPP6cJ5i1RLIMe596Se8lq4wnsRKwCoUkGkU4mzlj4_7":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#478, in:99.8%[Binance]/out:0%[-], ev=2, bal=6.5M
    "UQDsEWFbBRGimZcB8hs00xnUKDjLOuyuDKtedBoVqOHsdm-q":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#491, in:100.0%[Binance]/out:0%[-], ev=1, bal=6.3M
    "UQDsn5Sv9RIjBGytbIBLcBcNtM_j0o0vq4nO_3mrorfFo_OX":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#501, in:82.5%[Binance]/out:0%[-], ev=14, bal=6.2M
    "UQBlddzSZ2gTmF534guur6qExDzLUrt1K8ErcbGwwhODHe5b":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#509, in:80.9%[Binance]/out:0%[-], ev=11, bal=6.1M
    "UQDoZbmdwcaQ_ChC6io681SAL0p1EvvAGfNmbe3dD5cDjYV0":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#515, in:100.0%[Gate.io]/out:0%[-], ev=1, bal=6.1M
    "UQDf-g5AU9CwUiWpLcD6KilRkVM7cTLfv7sYCCC5i_36TTxy":
        {"name": "Gate.io Cold", "kind": "cex"},
    # rank#518, in:100.0%[Binance]/out:0%[-], ev=2, bal=6.0M
    "UQAM7neInG9akbVPY3vFFSDXbsZ2elu-LhL-lVSHQxhTZldq":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#519, in:100.0%[OKX]/out:100.0%[OKX], ev=12, bal=6.0M
    "UQA2ogqg4sy7KfGuQVXWtbOm3vnE7NVGCeBCl6-XdJkqy3pq":
        {"name": "OKX Internal", "kind": "cex"},
    # rank#533, in:100.0%[Binance]/out:0%[-], ev=2, bal=5.8M
    "UQD43kP-yXDGBuEty7-inqvIp46iirQJt2sG99J5DyoymvnN":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#543, in:92.0%[Binance]/out:0%[-], ev=19, bal=5.6M
    "UQAODzhtWtvM2U1cFeYHsbExTVvkPKHrWyC8Ie0yQk5uorKz":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#545, in:100.0%[Bitget]/out:0%[-], ev=3, bal=5.6M
    "UQCGLIrEiUHtJtq9QnfWIcYbczYX3i1LoEQTUNMRGAr8nsm1":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#547, in:100.0%[OKX]/out:0%[-], ev=5, bal=5.6M
    "UQCodhLBc_Oin7zqfQvDZ-jNKL7UBmMISSf7LSXvHRkM-tBQ":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#549, in:100.0%[OKX]/out:0%[-], ev=2, bal=5.6M
    "UQCkzr6utJHxYmc3ef7nPlNILnMuDJsqRRJtWAyNhq_ulBIY":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#565, in:52.3%[Bitget]/out:98.0%[OKX], ev=24, bal=5.4M
    "UQDj1q0RjYWsEMWw7l1QD3wVrwPg4XC36yEEGiJPKu0uVsn6":
        {"name": "OKX Deposit", "kind": "cex"},
    # rank#577, in:100.0%[OKX]/out:99.6%[OKX], ev=286, bal=5.2M
    "UQAauCzaEl-jJLi3Dc0Dqf2HtqIvJzLa9uK-dm931UjtcJwv":
        {"name": "OKX Internal", "kind": "cex"},
    # rank#583, in:100.0%[Binance]/out:0%[-], ev=1, bal=5.2M
    "UQAIUE9p6aP7ArvuLzwSNUgx-b2EzRRJ5-sGF9xxMHzypXnS":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#599, in:87.3%[OKX]/out:0%[-], ev=28, bal=5.1M
    "UQAm5QdcGhLAVyeiwievd6o3kN709rLnyDpX5WUe6GDUPrLi":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#620, in:71.0%[Binance]/out:90.6%[OKX], ev=33, bal=5.0M
    "UQBfHxmUSNPYhAdn8qfvc_ajvuv3T7wwR97nOngCxRvZnLwm":
        {"name": "OKX Deposit", "kind": "cex"},
    # rank#621, in:99.8%[OKX]/out:84.6%[OKX], ev=6, bal=5.0M
    "UQCbCZBPnYMYomapYp1SXAOvssb2r7-yXBYmZGkSAiE5RskQ":
        {"name": "OKX Internal", "kind": "cex"},
    # rank#632, in:100.0%[Binance]/out:0%[-], ev=3, bal=5.0M
    "UQAQfHIo7X2g68tY77QR6165uLJnit11STF1GW20OX_NTdUQ":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#647, in:100.0%[MEXC]/out:0%[-], ev=2, bal=4.9M
    "UQCAecf1ACdPv7NGnA9NGb1Hv3IJxDIWc9rWKpjeMOmbY44w":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#654, in:100.0%[Telegram Wallet]/out:0%[-], ev=8, bal=4.7M
    "UQAWYtCmKR1usM3Z_v2zBjarP_PGM7D-fZCJssjChlmepGAc":
        {"name": "Telegram Wallet Cold", "kind": "cex"},
    # rank#658, in:80.4%[MEXC]/out:0%[-], ev=2, bal=4.7M
    "UQBK_u0nsBW-LJrI8cNOR57F3pcs9_UXuoP3i-5KCN-CP1pE":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#664, in:100.0%[MEXC]/out:0%[-], ev=16, bal=4.6M
    "UQBDyteAMO6l53QGDaJNWMGs3me4x5y29eHkrkgae--wYixm":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#665, in:97.9%[Binance]/out:0%[-], ev=15, bal=4.6M
    "UQAC5G3Dthc3vHzKhtPvbmiusbURR9n4EPvCMJR-OhzF30c6":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#670, in:96.0%[Binance]/out:0%[-], ev=2, bal=4.6M
    "UQDh_QbzMENaZG189Y5ZFbzV5miaSR79Zc66dZosetmC72dd":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#688, in:88.7%[Binance]/out:0%[-], ev=47, bal=4.5M
    "UQCclTV4tr_yl5lIlVDF2ez-UQqddN-WLXLICUTJBsa5ex6h":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#694, in:100.0%[Binance]/out:0%[-], ev=1, bal=4.4M
    "UQClmpYGx1_yIxcs9Uztjs6Q7t-1BK3gz3I1WC3WsUwV7gj7":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#695, in:100.0%[MEXC]/out:0%[-], ev=3, bal=4.4M
    "UQCht6Pqy53p4xta2IsIuFodYHRb4SGmZD_HZki8V_6L8gOd":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#701, in:100.0%[lbank.info]/out:0%[-], ev=1, bal=4.4M
    "UQAv5LdrtfmkN4MC8lL0iKY2uYC9Q33lG_3OnszjRE6yq4dy":
        {"name": "lbank.info Cold", "kind": "cex"},
    # rank#714, in:90.6%[MEXC]/out:0%[-], ev=7, bal=4.3M
    "UQAqPRIm5UUYvwhBlprnwm_fQp80KiW0RWv1Vx5AOWDYqiRM":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#723, in:98.7%[OKX]/out:0%[-], ev=3, bal=4.2M
    "UQAYlYkBnlZyEHauqurmNy-MsIgIUbkyTWTo0hOW4uhIb6zy":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#728, in:100.0%[Binance]/out:0%[-], ev=4, bal=4.2M
    "UQCSn_bBUbw0SBxR1OfzZA2r3wOqgW1jDa8pbMJXn0TNhCNe":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#735, in:100.0%[Rapira]/out:0%[-], ev=3, bal=4.1M
    "UQC5dWiiQY5O5kQo22LqreByJNlPV2nTfn7dDKI1vyh3QTkA":
        {"name": "Rapira Cold", "kind": "cex"},
    # rank#736, in:100.0%[Bitget]/out:0%[-], ev=2, bal=4.1M
    "UQClf4P2mVixJB8QPa9yA0fiLfezCueS4Hl51UWqwKx-RRZo":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#741, in:100.0%[OKX]/out:0%[-], ev=3, bal=4.1M
    "UQCypKI3y88KN4zW0ASVlMbnYWPPapRucD9soDhYTAOpe8yl":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#743, in:100.0%[Binance]/out:0%[-], ev=5, bal=4.1M
    "UQD5WeMUd0p3VotBUOW2I18YK2UtW_17bzLNuCKyxuJSXjKK":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#747, in:99.2%[Binance]/out:0%[-], ev=13, bal=4.0M
    "UQDJ2TOEiCX7bY85Is3KWPZnQOGBLtiGzw5mlOQaqicCfy7i":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#752, in:100.0%[Binance]/out:0%[-], ev=24, bal=4.0M
    "UQC4qk7BVnRn_zlOVSRU-DPyi_F5uTsXgm5jEYljxaJKNm70":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#757, in:100.0%[MEXC]/out:0%[-], ev=6, bal=4.0M
    "UQA28xxzOBrOEqQB9tRfrAe8JWwqeqCTFLeLvQo1ISnxUCCH":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#759, in:100.0%[Binance]/out:0%[-], ev=2, bal=4.0M
    "UQAjvddqEk-7AzXdMWuUHBzPDEBQ0Y6HSlIwxB_hoIEy3nxz":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#775, in:100.0%[Binance]/out:0%[-], ev=3, bal=3.9M
    "UQA5En1_Bw9CWzH5I4UGdAoiUZN_mue5FHgY1ctZLxUFqma4":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#784, in:100.0%[Binance]/out:0%[-], ev=10, bal=3.9M
    "UQCtJEbppklHiQOi7wc67ca63gl0yjYFVjtvTcco0MjZ6Utp":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#808, in:100.0%[Binance]/out:0%[-], ev=5, bal=3.7M
    "UQCJyRv1fNqLmxmg6tSrjDb5WvnWLiRpLwmODsKnCP5eY624":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#810, in:100.0%[MEXC]/out:0%[-], ev=3, bal=3.7M
    "UQCLZQsUJTIKkFOW8Bw0urD9wFH_-rzkLBNXMp3ovbqdb1VB":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#811, in:100.0%[Bitget]/out:0%[-], ev=2, bal=3.7M
    "UQBIXC7C9h57eupMne8R7naaQgqsaKvH4GdZnSqH-KGtbyN8":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#812, in:100.0%[Binance]/out:0%[-], ev=10, bal=3.7M
    "UQBLZLh_O8PHcoZTuDtA6FcGWXdMtMpVj_4XiwrBFT1c3uuD":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#816, in:100.0%[Binance]/out:0%[-], ev=5, bal=3.7M
    "UQAl05JB2nB72TdISnaDRfwh3W6GMQx0U0idHt2rBU4cqZFS":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#819, in:100.0%[Binance]/out:0%[-], ev=2, bal=3.7M
    "UQCEqkax9N0JZ-kH-rZNxW_--HjnbiA7TA-mhYbNM6WqqYHD":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#820, in:100.0%[MEXC]/out:0%[-], ev=9, bal=3.7M
    "UQCQeJf0sfgsbHzTZh2sEeayt9-EIW8w48soCjF7TLNS8AOM":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#833, in:100.0%[MEXC]/out:0%[-], ev=1, bal=3.6M
    "UQBCYWVUnWf2pMoOVgZbRdHN_xpcggsu7BZDrZs1N5xaxKVd":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#839, in:88.8%[Binance]/out:0%[-], ev=11, bal=3.6M
    "UQCvl7MwZ7MBKbmNMfM4FveSMcwDNVmX2SeR3-LgONTv498c":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#841, in:100.0%[MEXC]/out:0%[-], ev=1, bal=3.6M
    "UQB45ogFK3sf1dseYO0aakV2_BZPc2MPgkF0X9be6FHGoSg9":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#842, in:99.0%[Binance]/out:0%[-], ev=5, bal=3.6M
    "UQBV7MMe1T6hUXDYNa_7_IsJtF7TIxvRt8jo9mlyYi_I4Ppp":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#849, in:100.0%[MEXC]/out:0%[-], ev=1, bal=3.6M
    "UQAQRUqj7T_2vz2kW0kThfz05bFsvxx94S0Pf7uXnp_biRIg":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#854, in:91.5%[MEXC]/out:0%[-], ev=6, bal=3.5M
    "UQAzXx41Bs6TUppE3-ktNplrl4osR_ppu9L0FsJdxVGF4vzW":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#864, in:100.0%[MEXC]/out:0%[-], ev=1, bal=3.5M
    "UQCBy_4sHXCUKkStfRjhi2v00WLe9ZHkJOXQJ0nSBpUQjtSH":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#865, in:100.0%[Binance]/out:0%[-], ev=1, bal=3.5M
    "UQAbl_9Btx9222md1ddQnU4LZICOccmdCOkE1fVEpzoLBVTd":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#875, in:100.0%[Binance]/out:0%[-], ev=1, bal=3.4M
    "UQCA5YPQPzr9blo-uQaataBFiN-lpZ-KWtoexPbkZaMTuSY_":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#876, in:100.0%[MEXC]/out:0%[-], ev=1, bal=3.4M
    "UQDWbtIP3CENt1S1KFz273A4MQYY7KlINfIhD4dHCVhaG17s":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#883, in:100.0%[MEXC]/out:0%[-], ev=1, bal=3.4M
    "UQC80S-Rf17hm8WpU3p7mmDH5pIwMunK90IVpKeoMMekmSxA":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#890, in:100.0%[Binance]/out:0%[-], ev=29, bal=3.3M
    "UQDjIKl9xerLccwMBTUUF-i7aq5gqGv9Tho9vi4AihpxVLQY":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#895, in:100.0%[Binance]/out:0%[-], ev=1, bal=3.3M
    "UQARpt7JNUq5GXfAPhc4vXzOVCF9YmWoyajBEX-EtaTlNCcn":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#899, in:84.7%[OKX]/out:0%[-], ev=3, bal=3.3M
    "UQCvcDP7FGFQBTNpZitUSipRaCiIpyQP21jvELWdyNPUCVFQ":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#900, in:100.0%[OKX]/out:0%[-], ev=5, bal=3.3M
    "UQBrrLhxOBag3TsvyXIZij-htAqkJwe1gmk2TI3IZTBLcDG9":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#902, in:100.0%[OKX]/out:0%[-], ev=3, bal=3.3M
    "UQCxbIZF7H0LZnyy4jgVrSC6KeJzXeKvz2axi6AfJNQYrY3i":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#924, in:100.0%[MEXC]/out:0%[-], ev=2, bal=3.2M
    "UQA5d2wR1bbjTsRuANxBUzzOjm2gwKjhurQLBl38LN10ltiT":
        {"name": "MEXC Cold", "kind": "cex"},
    # rank#932, in:100.0%[Bitget]/out:0%[-], ev=2, bal=3.2M
    "UQC0J-99ktwFXhwJuTAoRKDWFpI5NhZPO8aqZskH6uajJneY":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#933, in:93.5%[Binance]/out:0%[-], ev=6, bal=3.2M
    "UQDaWIelcziGencW2TQT4mYEfQm4Dqoqxm94Yd15RPnEX3Yb":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#935, in:85.3%[Telegram Wallet]/out:0%[-], ev=77, bal=3.2M
    "UQAu37D834r987WKk8jSrwQYq_Uqwc-_K-r8YZXdt_YZmGRG":
        {"name": "Telegram Wallet Cold", "kind": "cex"},
    # rank#943, in:100.0%[Binance]/out:0%[-], ev=14, bal=3.1M
    "UQDN9E4TfqC6N3D5aDic-h5IgZk1jm7okMtVctAYTXtvoAmI":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#946, in:100.0%[Binance]/out:0%[-], ev=1, bal=3.1M
    "UQB9UzGf-4lppNDqeOE-_nx7pjAdD7liTPdOAECOjO_NX0Ci":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#950, in:100.0%[Binance]/out:0%[-], ev=1, bal=3.1M
    "UQD2iP78ecHdtsVdkJ_rxp9FbrqfjjhwdSV_WRDnzb13zLlU":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#953, in:100.0%[OKX]/out:0%[-], ev=4, bal=3.1M
    "UQCgyf7fEpCnGW_JM8t0LM7vWjj25Q-qDhlNTOPW7qAhyt4Y":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#973, in:100.0%[Bitget]/out:0%[-], ev=2, bal=3.1M
    "UQBTxgdCQEsoX0DaGHAgQVEF4ydw6BI7wsZzNm-ZdkQbpk4R":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#987, in:100.0%[Binance]/out:0%[-], ev=29, bal=3.0M
    "UQBbQksmWYXJQfM3roLpuaLFEvot7kxpH3Ue_lEDdTlNg0nm":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#989, in:100.0%[Binance]/out:0%[-], ev=2, bal=3.0M
    "UQCh559JMAnoVKk-bjRqlaHJQ00OB7B8-u0KIkfWsVvPxCpY":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#993, in:100.0%[Binance]/out:0%[-], ev=2, bal=3.0M
    "UQDXUALQZLi_XFZb_oXrNa_ssqTsTkujXXLo7M_ze_ixzH5p":
        {"name": "Binance Cold", "kind": "cex"},
}


def classify(name: str) -> str:
    n = (name or "").lower()
    is_domain = n.endswith(".ton") or n.endswith(".t.me")
    for kw in CEX_KEYWORDS:
        if kw in n:
            return "cex"
    # personal .ton / .t.me domains shouldn't match protocol keywords
    # (e.g. "notnotcoiner.ton", "durovfragment.t.me" are people, not protocols)
    if not is_domain:
        for kw in PROTOCOL_KEYWORDS:
            if kw in n:
                return "protocol"
    return "named"


def load_key():
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def to_uq(raw: str) -> str:
    wc, h = raw.split(":")
    payload = bytes([0x51, int(wc) & 0xFF]) + bytes.fromhex(h)
    crc = crc16_xmodem(payload)
    return base64.urlsafe_b64encode(payload + crc.to_bytes(2, "big")).decode()


def http(method, url, key, body=None):
    headers = {"Accept": "application/json", "User-Agent": "DuflatCEXDiscover/1.0"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def fetch_holders(target, key):
    rows = []
    offset = 0
    while len(rows) < target:
        limit = min(PAGE, target - len(rows))
        url = f"https://tonapi.io/v2/jettons/{JETTON}/holders?limit={limit}&offset={offset}"
        data = http("GET", url, key)
        addrs = data.get("addresses", [])
        if not addrs:
            break
        for h in addrs:
            owner = h.get("owner") or {}
            raw = owner.get("address") or h.get("address")
            if not raw:
                continue
            try:
                rows.append(to_uq(raw))
            except Exception:
                rows.append(raw)
            if len(rows) >= target:
                break
        offset += len(addrs)
        time.sleep(0.15 if key else 1.1)
    return rows


def bulk_accounts(addrs, key):
    out = {}
    for i in range(0, len(addrs), BULK):
        chunk = addrs[i:i + BULK]
        url = "https://tonapi.io/v2/accounts/_bulk"
        try:
            data = http("POST", url, key, {"account_ids": chunk})
        except urllib.error.HTTPError as e:
            print(f"  bulk {i}: HTTP {e.code} — skipping batch", file=sys.stderr)
            time.sleep(2)
            continue
        for acc in data.get("accounts", []):
            addr = acc.get("address")
            name = acc.get("name")
            is_scam = acc.get("is_scam", False)
            if not addr:
                continue
            try:
                addr_uq = to_uq(addr) if ":" in addr else addr
            except Exception:
                addr_uq = addr
            if name or is_scam:
                out[addr_uq] = {"name": name or "", "is_scam": is_scam}
        print(f"  bulk {i}/{len(addrs)} -> {len(out)} labeled so far")
        time.sleep(0.15 if key else 1.1)
    return out


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    key = load_key()
    print(f"key={'VAR(' + str(len(key)) + ')' if key else 'YOK'} target={target}")
    print("fetching holders...")
    addrs = fetch_holders(target, key)
    print(f"got {len(addrs)} addresses")
    print("querying account labels...")
    labels = bulk_accounts(addrs, key)

    # classify
    counts = {"cex": 0, "protocol": 0, "named": 0}
    for addr, meta in labels.items():
        meta["kind"] = classify(meta.get("name", ""))
        counts[meta["kind"]] += 1
    print(f"\n{len(labels)} labeled  |  cex={counts['cex']}  protocol={counts['protocol']}  named={counts['named']}")

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)
    print(f"saved -> {OUT_JSON}")

    # emit JS snippet for inline embedding in NOT.html
    items = sorted(labels.items(), key=lambda kv: (kv[1]["kind"], kv[1]["name"]))
    lines = ["const LABELS = {"]
    last_kind = None
    for addr, meta in items:
        if meta["kind"] != last_kind:
            lines.append(f"  // {meta['kind']}")
            last_kind = meta["kind"]
        name_js = json.dumps(meta["name"])
        lines.append(f'  "{addr}": {{ name: {name_js}, kind: "{meta["kind"]}" }},')
    lines.append("};")
    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"saved -> {OUT_JS}")


if __name__ == "__main__":
    main()
