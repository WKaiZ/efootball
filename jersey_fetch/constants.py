from gameplan.constants import DB_PATH

HEADERS = {"User-Agent": "Mozilla/5.0"}
HTTP_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DEBUG_HTML_DIR = "debug_html"

MANUAL_ID_OVERRIDES = {
    "argentina": {
        "nico gonzalez": {"player_id": "486031", "preserve_name": True},
        "emiliano martinez": {"player_id": "111873", "preserve_name": True},
        "flaco lopez": {"player_id": "844797", "preserve_name": True},
    },
    "australia": {
        "mohamed toure": {"player_id": "742770", "preserve_name": True},
    },
    "austria": {
        "hannes wolf": {"player_id": "321070", "preserve_name": True},
    },
    "myanmar": {
        "wai lin aung": {"player_id": "735947", "preserve_name": True},
    },
    "malaysia": {
        "endrick": {"player_id": "452164", "preserve_name": True},
    },
    "luxembourg": {
        "diego duarte": {"player_id": "885845", "preserve_name": True},
    },
    "hong-kong": {
        "dudu": {"player_id": "447999", "preserve_name": True},
        "juninho": {"player_id": "451232", "preserve_name": True},
        "fernando": {"player_id": "254761", "preserve_name": True},
    },
    "dpr-korea": {
        "hun ri": {"player_id": "551941", "preserve_name": True},
    },
    "brunei": {
        "abdul hariz": {"player_id": "577168", "preserve_name": True},
    },
    "chad": {
        "franky tchaouna": {"player_id": "1571727", "preserve_name": True},
    },
    "bolivia": {
        "roberto fernandez": {"player_id": "598101", "preserve_name": True},
        "moises villarroel": {"player_id": "431863", "preserve_name": True},
    },
    "brazil": {
        "joao pedro": {"player_id": "626724", "preserve_name": True},
        "gabriel": {"player_id": "435338", "preserve_name": True},
        "ederson": {"player_id": "607854", "preserve_name": True},
        "vitinho": {"player_id": "468249", "preserve_name": True},
        "pepe": {"player_id": "520662", "preserve_name": True},
        "pedro": {"player_id": "432895", "preserve_name": True},
        "allan": {"player_id": "126422", "preserve_name": True},
        "leo pereira": {"player_id": "288431", "preserve_name": True},
        "igor thiago": {"player_id": "739443", "preserve_name": True},
        "douglas luiz": {"player_id": "447661", "preserve_name": True},
        "carlos augusto": {"player_id": "585982", "preserve_name": True},
        "murillo": {"player_id": "1005649", "preserve_name": True},
        "zico": {"player_id": "117619", "preserve_name": True},
        "estevao": {"player_id": "1056993", "preserve_name": True},
        "wesley": {"player_id": "964580", "preserve_name": True},
        "dodo": {"player_id": "401529", "preserve_name": True},
        "ze roberto": {"player_id": "89", "preserve_name": True},
        "denilson": {"player_id": "7660", "preserve_name": True},
        "cassio": {"player_id": "50144", "preserve_name": True},
        "alisson": {"player_id": "105470", "preserve_name": True},
        "paulinho": {"player_id": "428791", "preserve_name": True},
        "alex sandro": {"player_id": "79960", "preserve_name": True},
        "rafael": {"player_id": "68097", "preserve_name": True},
        "otavio": {"player_id": "997947", "preserve_name": True},
        "danilo santos": {"player_id": "808509", "preserve_name": True},
        "serginho": {"player_id": "5819", "preserve_name": True},
    },
    "bulgaria": {
        "stanislav ivanov": {"player_id": "412537", "preserve_name": True},
    },
    "burkina-faso": {
        "lassina traore": {"player_id": "551695", "preserve_name": True},
        "mohamed konate": {"player_id": "457743", "preserve_name": True},
    },
    "cabo-verde": {
        "david costa": {"player_id": "1160599", "preserve_name": True},
        "ivanildo fernandes": {"player_id": "340524", "preserve_name": True},
    },
    "finland": {
        "fredrik jensen": {"player_id": "249157", "preserve_name": True},
    },
    "honduras": {
        "david ruiz": {"player_id": "914681", "preserve_name": True},
        "luis lopez": {"player_id": "314941", "preserve_name": True},
    },
    "jamaica": {
        "richard king": {"player_id": "909017", "preserve_name": True},
    },
    "portugal": {
        "pepe": {"player_id": "14132", "preserve_name": True},
        "andre silva": {"player_id": "198008", "preserve_name": True},
        "joao moutinho": {"player_id": "29364", "preserve_name": True},
    },
    "france": {
        "maxence lacroix": {"player_id": "434224", "preserve_name": True},
        "lucas hernandez": {"player_id": "281963", "preserve_name": True},
    },
    "spain": {
        "adama traore": {"player_id": "204103", "preserve_name": True},
        "victor munoz": {"player_id": "935231", "preserve_name": True},
        "roberto fernandez": {"player_id": "720518", "preserve_name": True},
        "pepelu": {"player_id": "328480", "preserve_name": True},
    },
    "italy": {
        "luca pellegrini": {"player_id": "346567", "preserve_name": True},
        "alessandro romano": {"player_id": "911224", "preserve_name": True},
    },
    "chile": {
        "carlos palacios": {"player_id": "571219", "preserve_name": True},
        "marcelo morales": {"player_id": "841340", "preserve_name": True},
        "nicolas fernandez": {"player_id": "549597", "preserve_name": True},
        "matias fernandez": {"player_id": "402519", "preserve_name": True},
        "diego sanchez": {"player_id": "179532", "preserve_name": True},
    },
    "china-pr": {
        "serginho": {"player_id": "329013", "preserve_name": True},
        "fernandinho": {"player_id": "230937", "preserve_name": True},
        "alan": {"player_id": "73460", "preserve_name": True},
    },
    "colombia": {
        "jhon solis": {"player_id": "742521", "preserve_name": True},
        "alvaro montero": {"player_id": "292985", "preserve_name": True},
        "david silva": {"player_id": "74071", "preserve_name": True},
        "richard rios": {"player_id": "735573", "preserve_name": True},
        "luis suarez": {"player_id": "424784", "preserve_name": True},
        "yeimar gomez andrade": {"player_id": "343359", "preserve_name": True},
        "juan mosquera": {"player_id": "659826", "preserve_name": True},
        "carlos cuesta": {"player_id": "474589", "preserve_name": True},
        "andres mosquera": {"player_id": "100379", "preserve_name": True},
        "sebastian gomez": {"player_id": "570522", "preserve_name": True},
    },
    "senegal": {
        "pape fall": {"player_id": "1176295", "preserve_name": True},
        "idrissa gueye": {
            "CF": {"player_id": "1178488", "preserve_name": True},
            "DMF": {"player_id": "126665", "preserve_name": True},
        },
        "souleymane basse": {"player_id": "1111045", "preserve_name": True},
        "el hadji malick diouf": {"player_id": "1111589", "preserve_name": True},
        "formose mendy": {"player_id": "649023", "preserve_name": True},
    },
    "mexico": {
        "luis gabriel rey": {"player_id": "686445", "preserve_name": True},
        "henry martin": {"player_id": "286339", "preserve_name": True},
        "erick sanchez": {"player_id": "370875", "preserve_name": True},
        "johan vasquez": {"player_id": "532937", "preserve_name": True},
        "german berterame": {"player_id": "401572", "preserve_name": True},
    },
    "romania": {
        "nicolae stanciu": {"player_id": "148372", "preserve_name": True},
    },
    "mali": {
        "mamadou fofana": {"player_id": "402004", "preserve_name": True},
        "ousmane camara": {"player_id": "804711", "preserve_name": True},
        "adama traore": {
            "RWF": {"player_id": "364405", "preserve_name": True},
            "AMF": {"player_id": "262608", "preserve_name": True},
        },
        "ousmane diallo": {"player_id": "1060545", "preserve_name": True},
        "mamadou doumbia": {"player_id": "1101539", "preserve_name": True},
    },
    "mozambique": {
        "domingues": {"player_id": "64298", "preserve_name": True},
        "nene": {"player_id": "615702", "preserve_name": True},
        "guima": {"player_id": "305425", "preserve_name": True},
    },
    "uruguay": {
        "luis suarez": {"player_id": "44352", "preserve_name": True},
        "sebastian caceres": {"player_id": "532389", "preserve_name": True},
        "jose luis rodriguez": {"player_id": "430339", "preserve_name": True},
        "emiliano martinez": {"player_id": "707447", "preserve_name": True},
        "agustin alvarez": {"player_id": "812625", "preserve_name": True},
        "fernando muslera": {"player_id": "58088", "preserve_name": True},
        "christhian stuani": {"player_id": "59323", "preserve_name": True},
        "maximiliano araujo": {"player_id": "572675", "preserve_name": True},
        "juan rodriguez vega": {"player_id": "1228231", "preserve_name": True},
    },
    "switzerland": {
        "joel monteiro": {"player_id": "410787", "preserve_name": True},
    },
    "denmark": {
        "filip jørgensen": {"player_id": "585323", "preserve_name": True},
    },
    "egypt": {
        "mohamed hamdi": {"player_id": "369901", "preserve_name": True},
        "trezeguet": {"player_id": "234189", "preserve_name": True},
    },
    "united-arab-emirates": {
        "fabio lima": {"player_id": "179054", "preserve_name": True},
    },
    "england": {
        "alex scott": {"player_id": "855256", "preserve_name": True},
    },
    "germany": {
        "jamie leweling": {"player_id": "518505", "preserve_name": True},
    },
    "guinea": {
        "sekou sylla": {"player_id": "587333", "preserve_name": True},
        "ousmane camara": {"player_id": "827950", "preserve_name": True},
    },
    "guatemala": {
        "antonio lopez": {"player_id": "599909", "preserve_name": True},
        "jose morales": {"player_id": "354673", "preserve_name": True},
        "luis moran": {"player_id": "690420", "preserve_name": True},
    },
    "guinea-bissau": {
        "beto": {"player_id": "595809", "preserve_name": True},
    },
    "iraq": {
        "hussein ali": {"player_id": "585325", "preserve_name": True},
        "ali jasim": {"player_id": "877672", "preserve_name": True},
    },
    "korea-republic": {
        "tae-hwan kim": {"player_id": "156009", "preserve_name": True},
        "tae-hyeon kim": {
            "CB": {"player_id": "645847", "preserve_name": True},
            "RB": {"player_id": "508366", "preserve_name": True},
        },
    },
    "kosovo": {
        "ermal krasniqi": {"player_id": "606893", "preserve_name": True},
    },
    "usa": {
        "mauricio pineda": {"player_id": "345621", "preserve_name": True},
    },
    "venezuela": {
        "david martinez": {"player_id": "988222", "preserve_name": True},
        "daniel pereira": {"player_id": "856498", "preserve_name": True},
        "alexander gonzalez": {"player_id": "147562", "preserve_name": True},
        "ruben ramirez": {"player_id": "308810", "preserve_name": True},
    },
    "norway": {
        "patrik berg": {"player_id": "308439", "preserve_name": True},
    },
    "panama": {
        "cristian martinez": {"player_id": "419247", "preserve_name": True},
        "jose luis rodriguez": {"player_id": "425028", "preserve_name": True},
    },
    "st-vincent-and-grenadines": {
        "andrew johnson": {"player_id": "1305202", "preserve_name": True},
    },
    "timor-leste": {
        "joao pedro": {"player_id": "632164", "preserve_name": True},
    },
    "paraguay": {
        "diego gomez": {"player_id": "996897", "preserve_name": True},
        "juan caceres": {"player_id": "756494", "preserve_name": True},
    },
    "scotland": {
        "liam kelly": {"player_id": "208772", "preserve_name": True},
    },
}

EXCLUDE_FROM_ESPN_RECENT = frozenset(
    {
        "el-hadji diouf",
        "el hadji diouf",
        "fernando torres",
        "rui costa",
    }
)

ESPN_TEAM_NAME_ALIASES = {
    "bosnia and herzegovina": ("Bosnia-Herzegovina",),
    "cabo verde": ("Cape Verde",),
    "china pr": ("China", "PR China"),
    "congo dr": ("Democratic Republic of the Congo", "DR Congo"),
    "cote d'ivoire": ("Ivory Coast",),
    "czechia": ("Czech Republic",),
    "united arab emirates": ("UAE",),
    "republic of ireland": ("Ireland",),
    "ir iran": ("Iran",),
    "korea republic": ("South Korea", "Korea"),
    "brunei darussalam": ("Brunei",),
    "congo": ("Republic of the Congo", "Congo Republic"),
    "dpr korea": ("North Korea", "Korea DPR"),
    "the gambia": ("Gambia",),
    "guinea-bissau": ("Guinea Bissau",),
    "kyrgyz republic": ("Kyrgyzstan",),
    "north macedonia": ("Macedonia",),
    "serbia": ("Yugoslavia", "Serbia and Montenegro"),
    "türkiye": ("Turkiye", "Turkey"),
    "st. kitts and nevis": ("Saint Kitts and Nevis", "St Kitts And Nevis"),
    "st. lucia": ("Saint Lucia", "St Lucia"),
    "st. vincent and the grenadines": (
        "Saint Vincent and the Grenadines",
        "St Vincent And Grenadines",
    ),
    "timor-leste": ("Timor Leste",),
    "usa": ("United States",),
}

ESPN_TEAM_ID_OVERRIDES = {
    "jordan": "2917",
}

COUNTRY_DISPLAY_NAMES = {
    "bosnia-and-herzegovina": "Bosnia and Herzegovina",
    "cabo-verde": "Cabo Verde",
    "china-pr": "China PR",
    "congo-dr": "Congo DR",
    "ir-iran": "IR Iran",
    "republic-of-ireland": "Republic of Ireland",
    "cote-divoire": "Côte d'Ivoire",
    "korea-republic": "Korea Republic",
    "turkiye": "Türkiye",
    "united-arab-emirates": "United Arab Emirates",
    "brunei": "Brunei Darussalam",
    "congo": "Congo",
    "dpr-korea": "DPR Korea",
    "gambia": "The Gambia",
    "guinea-bissau": "Guinea-Bissau",
    "kyrgyz-republic": "Kyrgyz Republic",
    "st-kitts-and-nevis": "St. Kitts and Nevis",
    "st-lucia": "St. Lucia",
    "st-vincent-and-grenadines": "St. Vincent and the Grenadines",
    "timor-leste": "Timor-Leste",
}

PLAYER_NAME_ALIASES = {
    "argentina": [
        ("Flaco López", "José Manuel López"),
        ("Equi Fernández", "Ezequiel Fernández"),
    ],
    "brazil": [
        ("Jair Cunha", "Jair Paula"),
        ("Pedro Morisco", "Pedro Luccas"),
    ],
    "denmark": [
        ("Rasmus Nissen Kristensen", "Rasmus Kristensen"),
    ],
    "egypt": [
        ("Oufa Shobeir", "Mostafa Shoubir", "Mostafa Shobeir"),
    ],
    "greece": [
        ("Konstantinos Tsimikas", "Kostas Tsimikas"),
    ],
    "japan": [
        ("Ko Itakura", "Kou Itakura"),
        ("Leo Kokubo", "Leo Brian Kokubo", "Kokubo Leo Brian"),
    ],
    "scotland": [
        ("Andrew Robertson", "Andy Robertson"),
    ],
    "uruguay": [
        ("Juan Rodríguez Vega", "Juan Rodríguez"),
    ],
    "venezuela": [
        ("Cristian Cásseres", "Cristian Cásseres Jr."),
    ],
    "wales": [
        ("Jay Dasilva", "Jay Da Silva"),
    ],
    "ir-iran": [
        ("Seyed Hossein Hosseini", "Hossein Hosseini"),
        ("Seyed Mohammad Karimi", "Mohammad Karimi"),
        ("Dennis Eckert Ayensa", "Dennis Dargahi"),
    ],
    "bolivia": [
        ("Miguelito", "Miguel Terceros"),
    ],
    "luxembourg": [
        ("Tiago Pereira Cardoso", "Tiago Pereira"),
    ],
    "ecuador": [
        ("José Andrés Hurtado", "José Hurtado"),
    ],
    "china-pr": [
        ("Tyias Browning", "Jiang Guangtai"),
    ],
    "benin": [
        ("Sessi D Almeida", "Sessi D'Almeida"),
    ],
    "iceland": [
        ("Hákon Arnar Haraldsson", "Hakon Haraldsson"),
        ("Daníel Leó Grétarsson", "Daniel Gretarsson"),
        ("Brynjar Ingi Bjarnason", "Brynjar Bjarnason"),
    ],
    "uzbekistan": [
        ("Odildzhon Khamrobekov", "Odiljon Xamrobekov"),
    ],
    "gabon": [
        ("Michel Mboula", "Urie-Michel Mboula"),
    ],
    "palestine": [
        ("Mus'ab Al-Batat", "Musab Battat"),
    ],
    "israel": [
        ("Gabi Kanichowsky", "Gavriel Kanichowsky"),
    ],
}

POSITION_SEARCH_PHRASES = {
    "GK": "goalkeeper",
    "CB": "center back",
    "LB": "left back",
    "RB": "right back",
    "LWB": "left wing back",
    "RWB": "right wing back",
    "DMF": "defensive midfielder",
    "CMF": "central midfielder",
    "AMF": "attacking midfielder",
    "LMF": "left midfielder",
    "RMF": "right midfielder",
    "LWF": "left wing forward",
    "RWF": "right wing forward",
    "CF": "center forward",
    "SS": "second striker",
}

TRANSFERMARKT_PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_TRANSFERMARKT_STEALTH_JS = (
    "\nObject.defineProperty(navigator, 'webdriver', { get: () => undefined });\n"
)
