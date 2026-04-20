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
    },
    "brazil": {
        "gabriel": {"player_id": "435338", "preserve_name": True},
        "ederson": {"player_id": "607854", "preserve_name": True},
        "vitinho": {"player_id": "468249", "preserve_name": True},
        "pepe": {"player_id": "520662", "preserve_name": True},
        "pedro": {"player_id": "432895", "preserve_name": True},
        "allan": {"player_id": "126422", "preserve_name": True},
        "oscar": {"player_id": "85314", "preserve_name": True},
        "leo pereira": {"player_id": "288431", "preserve_name": True},
        "igor thiago": {"player_id": "739443", "preserve_name": True},
        "joao gomes": {"player_id": "735570", "preserve_name": True},
        "gerson": {"player_id": "341705", "preserve_name": True},
        "fred": {"player_id": "191614", "preserve_name": True},
        "douglas luiz": {"player_id": "447661", "preserve_name": True},
    },
    "portugal": {
        "pepe": {"player_id": "14132", "preserve_name": True},
    },
    "france": {
        "maxence lacroix": {"player_id": "434224", "preserve_name": True},
    },
    "spain": {
        "pedro": {"player_id": "65278", "preserve_name": True},
    },
    "italy": {
        "luca pellegrini": {"player_id": "346567", "preserve_name": True},
    },
    "colombia": {
        "david silva": {"player_id": "74071", "preserve_name": True},
        "richard rios": {"player_id": "159497", "preserve_name": True},
        "luis suarez": {"player_id": "424784", "preserve_name": True},
        "dani torres": {"player_id": "93142", "preserve_name": True},
    },
    "senegal": {
        "idrissa gueye": {"CF": {"player_id": "1178488", "preserve_name": True}},
        "souleymane basse": {"player_id": "1111045", "preserve_name": True},
        "el hadji malick diouf": {"player_id": "1111589", "preserve_name": True},
        "formose mendy": {"player_id": "649023", "preserve_name": True},
    },
    "mexico": {
        "henry martin": {"player_id": "286339", "preserve_name": True},
        "guillermo martinez": {"player_id": "347932", "preserve_name": True},
        "erick sanchez": {"player_id": "370875", "preserve_name": True},
        "osvaldo rodriguez": {"player_id": "295426", "preserve_name": True},
        "johan vasquez": {"player_id": "532937", "preserve_name": True},
        "felipe rodriguez": {"player_id": "102699", "preserve_name": True},
        "ivan lopez": {"player_id": "370861", "preserve_name": True},
    },
    "uruguay": {
        "luis suarez": {"player_id": "44352", "preserve_name": True},
        "sebastian caceres": {"player_id": "532389", "preserve_name": True},
        "jose luis rodriguez": {"player_id": "430339", "preserve_name": True},
        "emiliano martinez": {"player_id": "707447", "preserve_name": True},
        "agustin alvarez": {"player_id": "812625", "preserve_name": True},
    },
    "switzerland": {
        "dominik schmid": {"player_id": "359409", "preserve_name": True},
    },
    "usa": {
        "patrick agyemang": {"player_id": "1089574", "preserve_name": True},
    },
}

ESPN_NATIONAL_TEAM_ID_OVERRIDES = {
    "italy": "162",
}

EXCLUDE_FROM_ESPN_RECENT = frozenset(
    {
        "el-hadji diouf",
        "el hadji diouf",
        "fernando torres",
        "rui costa",
    }
)

ESPN_LINEUP_MANUAL_ROLES = {
    "ivan perisic": frozenset({"D"}),
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
