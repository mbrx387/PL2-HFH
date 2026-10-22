"""Pure source-to-CSV transformations, adapted from the supplied import script."""

import ast
import json


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def parse_contacts(value):
    emails = []
    phones = []
    if value is None:
        return (emails, phones)
    if isinstance(value, list):
        contacts = value
    elif isinstance(value, str):
        value = value.strip()
        if not value:
            return (emails, phones)
        try:
            contacts = json.loads(value)
        except ValueError:
            try:
                contacts = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return (emails, phones)
        if not isinstance(contacts, list):
            return (emails, phones)
    else:
        return (emails, phones)
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        email = contact.get("email")
        telephone = contact.get("telephone") or contact.get("phone")
        if email:
            email = str(email).strip()
            if email and email not in emails:
                emails.append(email)
        if telephone:
            telephone = str(telephone).strip()
            if telephone and telephone not in phones:
                phones.append(telephone)
    return (emails, phones)


def extract_contacts(item):
    emails = []
    phones = []
    for field in ["contact", "contacts", "contact_data", "contactData"]:
        value = item.get(field)
        if value:
            e, p = parse_contacts(value)
            emails.extend(e)
            phones.extend(p)
    direct_email = item.get("email") or item.get("mail")
    direct_phone = item.get("telephone") or item.get("phone")
    if direct_email:
        emails.append(str(direct_email).strip())
    if direct_phone:
        phones.append(str(direct_phone).strip())
    emails = list(dict.fromkeys(x for x in emails if x))
    phones = list(dict.fromkeys(x for x in phones if x))
    return ("; ".join(emails), "; ".join(phones))


def get_service_text(item):
    values = []
    fields = ["service_types", "services", "serviceTypes", "description", "name"]
    for field in fields:
        value = item.get(field)
        if value is None:
            continue
        if isinstance(value, list):
            for element in value:
                if isinstance(element, dict):
                    for v in element.values():
                        if v:
                            values.append(str(v))
                else:
                    values.append(str(element))
        elif isinstance(value, dict):
            for v in value.values():
                if v:
                    values.append(str(v))
        else:
            values.append(str(value))
    return " ".join(values).lower()


def detect_services(item):
    text = get_service_text(item)
    result = {
        "pflegestuetzpunkt": 0,
        "pflegeberatung": 0,
        "wohnberatung": 0,
        "demenzberatung": 0,
        "angehoerigenberatung": 0,
        "betreuungsberatung": 0,
    }
    services = []
    if "pflegestützpunkt" in text or "pflegestuetzpunkt" in text:
        result["pflegestuetzpunkt"] = 1
        services.append("Pflegestützpunkt")
    if "pflegeberatung" in text or "pflege beratung" in text:
        result["pflegeberatung"] = 1
        services.append("Pflegeberatung")
    if "wohnberatung" in text or "wohn beratung" in text:
        result["wohnberatung"] = 1
        services.append("Wohnberatung")
    if "demenzberatung" in text or "demenz beratung" in text:
        result["demenzberatung"] = 1
        services.append("Demenzberatung")
    if (
        "angehörigenberatung" in text
        or "angehoerigenberatung" in text
        or "pflegende angehörige" in text
        or ("pflegende angehoerige" in text)
    ):
        result["angehoerigenberatung"] = 1
        services.append("Angehörigenberatung")
    if "betreuungsberatung" in text or "betreuungs beratung" in text:
        result["betreuungsberatung"] = 1
        services.append("Betreuungsberatung")
    return (result, services)


def duplicate_key(item):
    zqp_id = clean_text(item.get("zqp_id"))
    if zqp_id:
        return "ZQP:" + zqp_id
    name = clean_text(item.get("name")).lower()
    adresse = clean_text(item.get("adresse")).lower()
    plz = clean_text(item.get("plz"))
    ort = clean_text(item.get("ort")).lower()
    return "LOCAL:" + name + "|" + adresse + "|" + plz + "|" + ort


def convert_item(item, eigene_id):
    email, telefon = extract_contacts(item)
    service_flags, services = detect_services(item)
    return {
        "unsere_id": eigene_id,
        "zqp_id": clean_text(item.get("id")),
        "name": clean_text(item.get("name")),
        "adresse": clean_text(item.get("address")),
        "plz": clean_text(item.get("zip")),
        "ort": clean_text(item.get("city")),
        "bundesland": clean_text(item.get("state")),
        "email": email,
        "telefon": telefon,
        "website": clean_text(item.get("url")),
        "latitude": item.get("lat"),
        "longitude": item.get("lng"),
        "pflegestuetzpunkt": service_flags["pflegestuetzpunkt"],
        "pflegeberatung": service_flags["pflegeberatung"],
        "wohnberatung": service_flags["wohnberatung"],
        "demenzberatung": service_flags["demenzberatung"],
        "angehoerigenberatung": service_flags["angehoerigenberatung"],
        "betreuungsberatung": service_flags["betreuungsberatung"],
        "leistungen": services,
        "zqp_raw": item,
        "updated_at": "",
    }
