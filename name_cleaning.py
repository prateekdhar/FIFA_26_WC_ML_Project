import re


EXACT_NAME_FIXES = {
    "Jean-RicnerJean Ricner Bellegarde": "Jean-Ricner Bellegarde",
    "El Hadji MalickEl Hadji Malick Diouf": "El Hadji Malick Diouf",
    "Milad Mohamm Adi": "Milad Mohammadi",
    "Amir Alamm Ari": "Amir Al-Ammari",
    "Mohamm Ad Abuhasheesh": "Mohammad Abuhasheesh",
    "Mohamm Ad Abuzraiq": "Mohammad Abuzraiq",
    "Mohamm Ad Abualnadi": "Mohammad Abualnadi",
    "Mohamm Ad Aldaoud": "Mohammad Aldaoud",
}


MC_NAME_FIXES = {
    "Mccowatt": "McCowatt",
    "Mcginn": "McGinn",
    "Mckennie": "McKennie",
    "Mckenna": "McKenna",
    "Mckenzie": "McKenzie",
    "Mclean": "McLean",
    "Mctominay": "McTominay",
}


def _fix_mc_token(match):
    token = "Mc" + match.group(1).lower().capitalize()
    return MC_NAME_FIXES.get(token, token)


def _title_mixed_caps_token(match):
    return match.group(0).capitalize()


def clean_player_name(name):
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    name = EXACT_NAME_FIXES.get(name, name)
    name = re.sub(r"\bMc([A-Z]{2,})\b", _fix_mc_token, name)
    name = re.sub(r"\b[A-Z][a-z]+[A-Z]{2,}\b", _title_mixed_caps_token, name)
    return EXACT_NAME_FIXES.get(name, name)
