"""
Lead Data Cleaning & Sorting Tool  (Raw Lead File -> Final Campaign File)
--------------------------------------------------------------------------

Implements the full workflow:
1. Standardize raw data (detect columns, split Full Name, rename, keep relevant fields)
2. Remove blank email records
3. Remove Indian contacts (by location/country + email domain)
4. Remove special characters & Unicode junk, trim spaces
5. Remove duplicates within file (by Email)
6. Remove records already in selected Master list(s) from the database (by Email)
7. Remove bounced emails from selected Bounce list(s) in the database (by Email)
7b/7c. Remove emails found in selected MQL / Unsub list(s) in the database (by Email)
8. Arrange final column sequence
9. Final quality check + summary report
10. Optionally save the cleaned contacts back into a Master list (database)

Master/Bounce suppression data lives in PostgreSQL (see db.py) and is managed on
the "Manage Suppression Database" page — it is no longer uploaded on each run.
"""

import codecs
import html
import io
import json
import re
import unicodedata
import zipfile
import gzip
import gc
import uuid
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
import xlsxwriter

import db
import theme
import Auth as auth

st.set_page_config(
    page_title="LeadFlow — Lead Data Cleaning",
    page_icon="⚡",
    layout="wide",
)

# -- Inject theme CSS & sidebar branding first, so the login screen below
#    (and every page) renders fully styled from the very first paint --
theme.inject_theme()
theme.inject_sidebar_title()

# --- Authentication gate ------------------------------------------------------
# Every page of the app requires a signed-in user. Master-database management
# is further restricted to admins on its own page (see auth.require_role).
auth.require_login()
auth.render_user_badge()

# --- Suppression database bootstrap ------------------------------------------
# Master/Bounce suppression data now lives in PostgreSQL (see db.py). Create the
# database + tables on first use; surface problems as a friendly banner instead
# of crashing, so cleaning can still run (with suppression skipped) if the DB is
# unavailable.
if not st.session_state.get("_db_ready"):
    _db_ok, _db_err = db.init_db()
    st.session_state["_db_ready"] = _db_ok
    st.session_state["_db_error"] = None if _db_ok else _db_err


def db_is_ready():
    return bool(st.session_state.get("_db_ready"))


def render_db_error_banner():
    err = st.session_state.get("_db_error") or "Unknown error"
    st.error(
        "⚠️ **The lead database isn't connected.** You can still clean files, but your saved "
        "lists (Master, Bounced, MQL, Unsubscribed) can't be excluded and results can't be "
        "saved until it's back."
    )
    with st.expander("How to fix this (for your administrator)", expanded=False):
        st.markdown(
            "1. Make sure **PostgreSQL is running**.\n"
            "2. Check your connection settings in `.streamlit/secrets.toml` "
            "(host, port, dbname, user, password).\n"
            "3. See the **README** for full setup steps.\n\n"
            f"**Technical details:** `{err}`"
        )
        if st.button("🔄 Retry database connection", key="retry_db_conn"):
            st.session_state.pop("_db_ready", None)
            st.session_state.pop("_db_error", None)
            st.rerun()


def cleaned_df_to_records(df):
    """Convert a cleaned DataFrame into contact dicts for db.upsert_master_contacts."""
    col_map = {
        "First Name": "first_name",
        "Last Name": "last_name",
        "Company": "company",
        "Email": "email",
        "Job Title": "job_title",
        "Industry": "industry",
        "Location": "location",
    }
    present_cols = [c for c in col_map if c in df.columns]
    keys = [col_map[c] for c in present_cols]
    records = []
    for row in df[present_cols].itertuples(index=False, name=None):
        records.append(dict(zip(keys, row)))
    return records


# -- Top bar (theme CSS & sidebar branding are injected above, before the
#    auth gate, so the login screen is themed too) --
st.markdown('<div class="lf-topbar">', unsafe_allow_html=True)
theme.render_topbar()
st.markdown('</div>', unsafe_allow_html=True)
theme.sidebar_nav(auth.current_user())


def _workflow_step():
    """Which step of the Upload → Review → Clean → Download strip the user is on."""
    if "cleaned_df" in st.session_state:
        return 3
    if st.session_state.get("active_raw_file") is not None:
        return 1
    return 0


# Drawn now and redrawn at the end of the run, so it reflects what this run did.
_stepper = st.empty()
theme.workflow_steps(_workflow_step(), _stepper)

if not db_is_ready():
    render_db_error_banner()


# Use shared section_header from theme module
def section_header(number, title, subtitle=None):
    theme.section_header(number, title, subtitle)



FIELD_HELP = {
    "Full Name": "If your file has one combined name column instead of separate First/Last, map it here — it will be auto-split.",
    "First Name": "Contact's first name.",
    "Last Name": "Contact's last name.",
    "Company": "The company or organization the contact works at.",
    "Email": "Required for every step — used to remove duplicates, existing contacts, and bounces.",
    "Job Title": "Contact's job title, designation, or role.",
    "Industry": "Optional. The company's industry or sector.",
    "Location": "Optional. City, state, or country — also used to detect and remove Indian contacts.",
}
 
FINAL_COLUMNS = ["First Name", "Last Name", "Company", "Email", "Job Title", "Industry", "Location"]
 
# Header synonyms used for auto-detecting columns in messy raw files
COLUMN_SYNONYMS = {
    "Full Name": ["full name", "fullname", "name", "contact name"],
    "First Name": ["first name", "firstname", "fname", "given name"],
    "Last Name": ["last name", "lastname", "lname", "surname", "family name"],
    "Company": ["company", "company name", "organization", "organisation", "employer"],
    "Email": ["email", "email address", "e-mail", "emailid", "email id"],
    "Job Title": ["job title", "title", "designation", "position", "role"],
    "Industry": ["industry", "sector", "vertical"],
    "Location": ["location", "city", "country", "region", "address", "state"],
}
 
INDIAN_STATE_CITY_HINTS = [
    "india", "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "surat", "jaipur", "lucknow", "kanpur",
    "nagpur", "indore", "gurgaon", "gurugram", "noida", "chandigarh", "kerala",
    "punjab", "maharashtra", "karnataka", "tamil nadu", "gujarat", "rajasthan",
    "uttar pradesh", "west bengal", "telangana", "andhra pradesh",
]
INDIAN_HINT_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(h) for h in INDIAN_STATE_CITY_HINTS) + r")\b"
)
 
 
SPECIAL_CHARS_PATTERN = re.compile(
    r"[ÃÂÄÅƒÙ¢€™žœ¦§µ¶®·¸»¼½¾¿ŸþÿΓÇ~*!#$%^?]"
)
# Combined pattern for fast vectorized counting: any non-ASCII char, or any of the
# specific ASCII symbols we strip. Equivalent in effect to count_special_chars() below,
# but usable directly with pandas .str.count() for speed on large files.
SPECIAL_CHARS_COUNT_PATTERN = re.compile(r"[^\x00-\x7F]|[~*!#$%^?]")

COUNTRIES_JSON_PATH = Path(__file__).parent / "data" / "countries.json"
MAX_UNCOMPRESSED_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_COMPRESSED_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_CONTENT_BYTES = 250 * 1024 * 1024

 
 
def normalize_header(col):
    return re.sub(r"[^a-z0-9]", "", str(col).lower())
 
 
def auto_map_columns(df):
    """Return {standard_name: actual_column_name_in_df} based on header synonyms."""
    mapping = {}
    normalized_cols = {normalize_header(c): c for c in df.columns}
    for standard, synonyms in COLUMN_SYNONYMS.items():
        for syn in synonyms:
            norm_syn = normalize_header(syn)
            if norm_syn in normalized_cols:
                mapping[standard] = normalized_cols[norm_syn]
                break
    return mapping
 
 
def count_special_chars(value):
    """Count special/junk characters in a value (special-char set + non-ASCII/control chars)."""
    if pd.isna(value):
        return 0
    text = str(value)
    count = len(SPECIAL_CHARS_PATTERN.findall(text))
    # Count non-ASCII characters not already covered by the pattern above
    for ch in text:
        if ord(ch) > 127 and not SPECIAL_CHARS_PATTERN.match(ch):
            count += 1
    return count
 
 
def clean_text(value):
    """Remove special/unicode junk, hidden non-printables, and trim spaces."""
    if pd.isna(value):
        return value
    text = str(value)
    # Remove specified special characters
    text = SPECIAL_CHARS_PATTERN.sub("", text)
    # Normalize unicode (decompose accented chars) then drop non-ASCII leftovers
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\n\t")
    text = text.encode("ascii", "ignore").decode("ascii")
    # Collapse multiple spaces, trim
    text = re.sub(r"\s+", " ", text).strip()
    # Remove stray leftover symbols like ~~ / ~ if any slipped through
    text = re.sub(r"~+", "", text).strip()
    return text


def value_has_special_chars(value):
    if pd.isna(value):
        return False
    text = str(value)
    return bool(SPECIAL_CHARS_COUNT_PATTERN.search(text))
 
 
def is_indian_contact(row, location_col, email_col, check_location=True, check_domain=True):
    """Row-wise version, kept for reference/testing. The app uses the vectorized
    find_indian_contacts() below for performance on large files."""
    location_val = str(row.get(location_col, "")).lower() if location_col else ""
    email_val = str(row.get(email_col, "")).lower() if email_col else ""
 
    if check_location and INDIAN_HINT_PATTERN.search(location_val):
        return True, "Location text", row.get(location_col, "")
 
    if check_domain and email_val.endswith(".in"):
        return True, "Email domain (.in)", row.get(email_col, "")
 
    return False, "", ""
 
 
def find_indian_contacts(std, location_col="Location", email_col="Email", check_location=True, check_domain=True):
    """Vectorized Indian-contact detection — fast on large (300k+ row) files.
    Returns (is_match_series, reason_series, matched_value_series)."""
    n = len(std)
    location_series = std[location_col].astype(str) if location_col in std.columns else pd.Series([""] * n, index=std.index)
    email_series = std[email_col].astype(str) if email_col in std.columns else pd.Series([""] * n, index=std.index)
 
    location_match = (
        location_series.str.lower().str.contains(INDIAN_HINT_PATTERN, regex=True, na=False)
        if check_location else pd.Series(False, index=std.index)
    )
    domain_match = (
        email_series.str.lower().str.endswith(".in", na=False)
        if check_domain else pd.Series(False, index=std.index)
    )
 
    is_match = location_match | domain_match
    reason = pd.Series("", index=std.index)
    reason[domain_match] = "Email domain (.in)"
    reason[location_match] = "Location text"  # location takes priority if both match
 
    matched_value = pd.Series("", index=std.index)
    matched_value[domain_match] = email_series[domain_match]
    matched_value[location_match] = location_series[location_match]
 
    return is_match, reason, matched_value
 
 
def normalize_place_text(value):
    text = str(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# US hints used to prevent false country matches when a location clearly indicates US.
US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming", "district of columbia",
}

US_STATE_ABBREVIATIONS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in",
    "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv",
    "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn",
    "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
}


def has_us_state_signal(parts, normalized_text):
    if any(part in US_STATE_NAMES for part in parts):
        return True

    # Also detect two-letter state abbreviations in tokenized location text.
    tokens = set(normalized_text.split())
    return any(token in US_STATE_ABBREVIATIONS for token in tokens)
 
 
@st.cache_resource(show_spinner=False)
def load_country_reference(json_path_str):
    path = Path(json_path_str)
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError("countries.json format is invalid. Expected top-level 'data' list.")

    countries = payload["data"]
    country_name_lookup = {}
    city_to_countries = {}

    # Common aliases that appear in lead files but differ from the canonical JSON names.
    alias_overrides = {
        "us": "United States",
        "u s": "United States",
        "usa": "United States",
        "u s a": "United States",
        "united states of america": "United States",
        "uk": "United Kingdom",
        "u k": "United Kingdom",
        "england": "United Kingdom",
        "scotland": "United Kingdom",
        "wales": "United Kingdom",
        "northern ireland": "United Kingdom",
        "uae": "United Arab Emirates",
        "u a e": "United Arab Emirates",
        "south korea": "Korea South",
        "north korea": "Korea North",
    }

    for item in countries:
        country = str(item.get("country", "")).strip()
        if not country:
            continue

        country_norm = normalize_place_text(country)
        if country_norm:
            country_name_lookup[country_norm] = country

        for city in item.get("cities", []):
            norm_city = normalize_place_text(city)
            if norm_city:
                city_to_countries.setdefault(norm_city, set()).add(country)

    alias_lookup = {}
    for alias_norm, canonical in alias_overrides.items():
        canonical_norm = normalize_place_text(canonical)
        canonical_country = country_name_lookup.get(canonical_norm)
        if canonical_country:
            alias_lookup[normalize_place_text(alias_norm)] = canonical_country

    city_alias_overrides = {
        "los angles": "los angeles",
        "los angelos": "los angeles",
        "newyork": "new york",
        "sanfrancisco": "san francisco",
    }
    city_alias_lookup = {
        normalize_place_text(k): normalize_place_text(v)
        for k, v in city_alias_overrides.items()
    }

    # Built once here (this function is cached) for the city fallback in
    # classify_country_from_location. City keys are space-separated [a-z0-9] tokens, so a
    # boundary-aware match inside a part is exactly a run of whole tokens equal to the key.
    # The rank keeps city_to_countries order, so the first matching city stays the same.
    city_rank = {
        city_key: (rank, countries_set)
        for rank, (city_key, countries_set) in enumerate(
            (k, v) for k, v in city_to_countries.items() if len(k) >= 4
        )
    }
    max_city_tokens = max((len(k.split()) for k in city_rank), default=0)

    return {
        "country_name_lookup": country_name_lookup,
        "alias_lookup": alias_lookup,
        "city_to_countries": city_to_countries,
        "city_alias_lookup": city_alias_lookup,
        "city_rank": city_rank,
        "max_city_tokens": max_city_tokens,
    }


def classify_country_from_location(location_text, country_ref):
    """Classify country from a free-form Location cell.

    Rules (in priority order):
    1. If a country name (or known alias) appears ANYWHERE in the location text,
       return that country immediately — city/state tokens are ignored.
    2. If no country name is found, scan the location parts LEFT-TO-RIGHT and
       return the country of the FIRST city that matches.
    3. If nothing matches, return "Unknown".
    """
    text_raw = str(location_text)
    normalized = normalize_place_text(text_raw)
    if not normalized:
        return "Unknown"

    country_name_lookup = country_ref["country_name_lookup"]
    alias_lookup = country_ref["alias_lookup"]
    city_to_countries = country_ref["city_to_countries"]
    city_alias_lookup = country_ref["city_alias_lookup"]

    # Split common location formats: "City, State, Country".
    raw_parts = re.split(r"[,;|/\\-]+", text_raw)
    parts = [normalize_place_text(p) for p in raw_parts if normalize_place_text(p)]
    parts = [city_alias_lookup.get(part, part) for part in parts]
    full_text = f" {normalized} "

    # Strong US indicators (country aliases + state names/abbreviations)
    explicit_us_alias_present = any(f" {alias_norm} " in full_text for alias_norm in ["us", "u s", "usa", "u s a", "united states", "united states of america"])
    us_state_present = has_us_state_signal(parts, normalized)

    # If the location explicitly says US/USA/U.S. or has a US state signal,
    # treat it as United States up front.
    if explicit_us_alias_present or us_state_present:
        us_country = country_name_lookup.get("united states") or alias_lookup.get("usa")
        if us_country:
            return us_country

    # 1) Prefer explicit country/state tokens in the parts (exact match or alias).
    for part in parts:
        if part in country_name_lookup:
            return country_name_lookup[part]
        if part in alias_lookup:
            return alias_lookup[part]

    # 2) Also check the full normalized text for a country phrase (handles
    #    cases like "State of X" or "Somewhere, United States").
    for country_norm, country in country_name_lookup.items():
        if f" {country_norm} " in full_text:
            return country
    for alias_norm, country in alias_lookup.items():
        if f" {alias_norm} " in full_text:
            return country

    # ── PRIORITY 2: City-based fallback — left-to-right, first match wins ────
    # Scan parts in the order they appear in the location string. The first
    # part that resolves to a known city is used immediately — no scoring.
    #
    # Important: avoid raw substring checks (city_key in part), because short
    # city tokens can create cross-country false positives (for example,
    # matching a tiny fragment inside a US state/city token).
    for part in parts:
        matched_countries = city_to_countries.get(part)
        if not matched_countries:
            # Boundary-aware phrase match: e.g. "san francisco bay area" →
            # "san francisco", while avoiding loose partial-fragment matches.
            # Looks up every run of whole tokens instead of scanning every city; the
            # lowest-ranked hit is the city the full scan would have found first.
            city_rank = country_ref["city_rank"]
            tokens = part.split()
            best = None
            for size in range(1, min(len(tokens), country_ref["max_city_tokens"]) + 1):
                for start in range(len(tokens) - size + 1):
                    hit = city_rank.get(" ".join(tokens[start:start + size]))
                    if hit and (best is None or hit[0] < best[0]):
                        best = hit
            if best:
                matched_countries = best[1]
        if matched_countries:
            # Return immediately on first city hit (deterministic left-to-right)
            if len(matched_countries) == 1:
                return next(iter(matched_countries))
            # Ambiguous city names: prefer United States when present.
            if "United States" in matched_countries:
                return "United States"
            # City shared by multiple countries — pick alphabetically for stability
            return sorted(matched_countries)[0]

    # ── No match — location present but not in countries.json ────────────────
    return "Unknown"


def classify_countries_fast(location_series, country_ref):
    """Country classification with city-priority matching.
    Vectorized via unique location mapping for ultra-fast performance on large datasets."""
    unique_locs = location_series.dropna().unique()
    loc_to_country = {loc: classify_country_from_location(loc, country_ref) for loc in unique_locs}
    loc_to_country[""] = "Unknown"
    return location_series.map(loc_to_country).fillna("Unknown")


def classify_countries(location_series, country_ref):
    return classify_countries_fast(location_series, country_ref)


def get_upload_size(file):
    size = getattr(file, "size", None)
    if size is not None:
        return int(size)
    return len(file.getvalue())

def validate_upload(file):
    """Return a user-facing error for uploads likely to exhaust process memory."""
    if file is None:
        return None

    filename = file.name.lower()
    upload_size = get_upload_size(file)
    is_compressed = filename.endswith((".zip", ".gz", ".gzip"))
    if upload_size > (MAX_COMPRESSED_UPLOAD_BYTES if is_compressed else MAX_UNCOMPRESSED_UPLOAD_BYTES):
        limit_mb = MAX_COMPRESSED_UPLOAD_BYTES if is_compressed else MAX_UNCOMPRESSED_UPLOAD_BYTES
        if is_compressed:
            return (
                f"'{file.name}' is larger than the {limit_mb // (1024 * 1024)} MB compressed-upload limit. "
                "Please split it into smaller ZIP/GZ files before uploading."
            )
        return (
            f"'{file.name}' is {upload_size / (1024 * 1024):,.1f} MB, which is too large to process safely. "
            "Please first convert it to a ZIP or GZ compressed file, then upload the compressed version."
        )

    if filename.endswith(".zip"):
        try:
            file.seek(0)
            with zipfile.ZipFile(file) as archive:
                data_files = [
                    info for info in archive.infolist()
                    if not info.is_dir()
                    and not info.filename.startswith("__MACOSX")
                    and info.filename.lower().endswith((".csv", ".xlsx", ".xls"))
                ]
                expanded_size = sum(info.file_size for info in data_files)
                if expanded_size > MAX_ARCHIVE_CONTENT_BYTES:
                    return (
                        f"'{file.name}' expands to more than {MAX_ARCHIVE_CONTENT_BYTES // (1024 * 1024)} MB. "
                        "Please split the source data into smaller ZIP/GZ files before uploading."
                    )
        except (OSError, zipfile.BadZipFile) as error:
            return f"Could not inspect '{file.name}' safely: {error}"
        finally:
            file.seek(0)

    if filename.endswith((".gz", ".gzip")):
        try:
            file.seek(0)
            expanded_size = 0
            with gzip.GzipFile(fileobj=file) as archive:
                while archive.read(1024 * 1024):
                    expanded_size += 1024 * 1024
                    if expanded_size > MAX_ARCHIVE_CONTENT_BYTES:
                        return (
                            f"'{file.name}' expands to more than {MAX_ARCHIVE_CONTENT_BYTES // (1024 * 1024)} MB. "
                            "Please split the source data into smaller ZIP/GZ files before uploading."
                        )
        except (OSError, EOFError) as error:
            return f"Could not inspect '{file.name}' safely: {error}"
        finally:
            file.seek(0)

    return None

def _is_valid_utf8(file, chunk_size=1 << 20):
    """True if the whole upload decodes as UTF-8. Streams it in chunks, keeping nothing."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    file.seek(0)
    try:
        while chunk := file.read(chunk_size):
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
        return True
    except UnicodeDecodeError:
        return False
    finally:
        file.seek(0)


def load_file_internal(file):
    """Load CSV, XLSX, XLS, or ZIP/GZ archives with memory-efficient parsing."""
    filename = file.name.lower()

    try:
        if filename.endswith(".zip"):
            with zipfile.ZipFile(file) as z:
                data_files = [f for f in z.namelist() if not f.startswith("__MACOSX") and f.lower().endswith((".csv", ".xlsx", ".xls"))]
                if not data_files:
                    raise ValueError(f"No CSV or Excel file found inside zip archive '{file.name}'.")
                with z.open(data_files[0]) as inner_f:
                    if data_files[0].lower().endswith(".csv"):
                        try:
                            return pd.read_csv(inner_f, encoding="utf-8", low_memory=False)
                        except (UnicodeDecodeError, UnicodeError):
                            inner_f.seek(0)
                            return pd.read_csv(inner_f, encoding="latin1", encoding_errors="replace", low_memory=False)
                    else:
                        return pd.read_excel(inner_f, engine="calamine")

        elif filename.endswith((".gz", ".gzip")):
            try:
                return pd.read_csv(file, compression="gzip", encoding="utf-8", low_memory=False)
            except (UnicodeDecodeError, UnicodeError):
                file.seek(0)
                return pd.read_csv(file, compression="gzip", encoding="latin1", encoding_errors="replace", low_memory=False)

        elif filename.endswith(".csv"):
            encodings_to_try = ["utf-8", "utf-8-sig", "cp1252", "latin1"]
            if not _is_valid_utf8(file):
                # Both UTF-8 attempts would fail, but only after parsing most of the file.
                encodings_to_try = ["cp1252", "latin1"]
            for enc in encodings_to_try:
                try:
                    file.seek(0)
                    return pd.read_csv(file, encoding=enc, low_memory=False)
                except (UnicodeDecodeError, UnicodeError):
                    continue
            file.seek(0)
            return pd.read_csv(file, encoding="latin1", encoding_errors="replace", low_memory=False)

        elif filename.endswith(".xlsx"):
            file.seek(0)
            # calamine reads the same values as openpyxl, several times faster.
            return pd.read_excel(file, engine="calamine")

        elif filename.endswith(".xls"):
            file.seek(0)
            return pd.read_excel(file, engine="calamine")

        else:
            raise ValueError(f"Unsupported file format: {file.name}. Please upload CSV, XLSX, XLS, ZIP, or GZ.")

    except MemoryError:
        if filename.endswith(".csv") or filename.endswith(".zip"):
            try:
                file.seek(0)
                chunks = []
                for chunk in pd.read_csv(file, encoding="latin1", encoding_errors="replace", chunksize=100_000, dtype=str):
                    chunks.append(chunk)
                if not chunks:
                    return pd.DataFrame()
                return pd.concat(chunks, ignore_index=True)
            except Exception as e:
                raise ValueError(f"Could not read large CSV file in streaming mode: {e}")
        raise
    except Exception as e:
        raise ValueError(f"Could not read file '{file.name}': {e}")


def load_file(file):
    """Zero-overhead cached loader using file identity to prevent memory hashing spikes."""
    if file is None:
        return None
    cache_key = f"_df_cache_{getattr(file, 'name', '')}_{getattr(file, 'size', 0)}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = load_file_internal(file)
    # Only the active raw file needs to stay in memory; release the one it replaced.
    prev_key = st.session_state.get("_raw_df_cache_key")
    if prev_key != cache_key:
        if prev_key:
            st.session_state.pop(prev_key, None)
        st.session_state["_raw_df_cache_key"] = cache_key
    return st.session_state[cache_key]


def validate_active_upload(file):
    """validate_upload() for the active raw file, remembered per upload: the answer can't
    change between reruns, and for .gz files each check decompresses the whole archive."""
    key = (getattr(file, "file_id", None), file.name, get_upload_size(file))
    cached = st.session_state.get("_active_upload_check")
    if not cached or cached[0] != key:
        cached = (key, validate_upload(file))
        st.session_state["_active_upload_check"] = cached
    return cached[1]


def get_email_series(df, mapping):
    email_col = mapping.get("Email")
    if email_col and email_col in df.columns:
        return df[email_col].astype(str).str.strip().str.lower()
    return pd.Series([""] * len(df))


# ---------------- LAZY DOWNLOAD HELPERS ----------------
# st.download_button accepts a callable for `data`; Streamlit only invokes it when the
# user actually clicks. Building CSV/XLSX bytes eagerly on every rerun was one of the
# main reasons each click felt slow, so every download below goes through these.
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def csv_bytes(df):
    """Return a zero-arg callable that serialises `df` to CSV bytes on demand."""
    return lambda: df.to_csv(index=False).encode("utf-8")


def xlsx_bytes(df):
    """The XLSX file pandas + openpyxl would write, built row by row with XlsxWriter (~2.5x faster).

    Text is stored with openpyxl's rule (a value starting with "=" and longer than one
    character becomes a formula) and missing values stay empty. Anything other than text
    or a missing value goes through the original pandas + openpyxl writer unchanged.
    """
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"strings_to_urls": False, "constant_memory": True})
    ws = wb.add_worksheet("Sheet1")

    def put(r, c, v):
        if len(v) > 1 and v.startswith("="):
            ws.write_formula(r, c, v)
        else:
            ws.write_string(r, c, v)

    plain = all(isinstance(c, str) for c in df.columns)
    if plain:
        for c, name in enumerate(df.columns):
            put(0, c, name)
        for r, row in enumerate(df.itertuples(index=False, name=None), start=1):
            for c, v in enumerate(row):
                if isinstance(v, str):
                    put(r, c, v)
                elif not (v is None or v is pd.NA or (isinstance(v, float) and v != v)):
                    plain = False
                    break
            if not plain:
                break
    wb.close()
    if plain:
        return buf.getvalue()
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def make_download(df, fmt, base_name):
    """Return (data_callable, file_name, mime) for the requested format ('csv', 'xlsx', 'zip')."""
    if fmt == "zip":
        def _build():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(f"{base_name}.csv", df.to_csv(index=False))
            return buf.getvalue()
        return _build, f"{base_name}.zip", "application/zip"
    if fmt == "xlsx":
        return (lambda: xlsx_bytes(df)), f"{base_name}.xlsx", XLSX_MIME
    return csv_bytes(df), f"{base_name}.csv", "text/csv"


def remove_downloaded_leads(downloaded_df, reset_keys=(), label="your selection"):
    """download_button on_click callback: drop the downloaded leads from the Final Campaign.

    Streamlit runs this once per click, before the rerun, so the removal is tied to the
    download itself rather than to the button being on screen. Leads are matched on the
    same trimmed, lower-cased Email used by the rest of the page. The file is built from
    the dataframe captured when the button was rendered, so replacing cleaned_df here
    can't change what the user receives. Downloading the same leads again is a no-op.
    """
    final_df = st.session_state.get("cleaned_df")
    if final_df is None or downloaded_df is None or downloaded_df.empty:
        return
    downloaded_emails = set(downloaded_df["Email"].astype(str).str.strip().str.lower())
    keep = ~final_df["Email"].astype(str).str.strip().str.lower().isin(downloaded_emails).to_numpy()
    removed = int(len(keep) - keep.sum())
    if removed == 0:
        return

    # Build every new value first and only then swap them in, so a failure part-way
    # leaves the Final Campaign exactly as it was.
    new_final = final_df[keep].reset_index(drop=True)
    old_token = st.session_state.get("run_token")
    new_token = uuid.uuid4().hex
    # Removing rows doesn't change whether the remaining leads are already in a Master
    # list, so the Save-to-Master preview is kept (re-aligned) instead of re-querying.
    dedup = st.session_state.get("_dedup_preview")
    new_dedup = None
    if dedup and dedup.get("key") == old_token and len(dedup["new_mask"]) == len(final_df):
        new_dedup = {"key": new_token, "new_mask": pd.Series(dedup["new_mask"].to_numpy()[keep])}
    country_series = st.session_state.get("country_series")
    new_country = None
    if country_series is not None and len(country_series) == len(final_df):
        new_country = country_series[keep].reset_index(drop=True)

    st.session_state["cleaned_df"] = new_final
    if new_country is not None:
        st.session_state["country_series"] = new_country
        st.session_state["country_counts"] = new_country.value_counts().to_dict()
    # Row positions changed, so masks cached against the old frame are stale.
    st.session_state["run_token"] = new_token
    st.session_state.pop("_dedup_preview", None)
    if new_dedup is not None:
        st.session_state["_dedup_preview"] = new_dedup
    for k in reset_keys:
        st.session_state[k] = False
    # Shown once, above the download tabs, on the rerun this click triggers.
    st.session_state["_split_download_done"] = (label, removed, len(new_final))


# ---------------- FILE UPLOADS ----------------
section_header(
    "01-Upload", "Upload your lead file",
    "Add a CSV or Excel file of leads. LeadFlow will clean it and get it ready for your campaign.",
)
st.markdown(
    '<div class="upload-card">📁 <strong>1.</strong> Drop your file in the box below &nbsp;·&nbsp; '
    '<strong>2.</strong> Tick the saved lists to exclude &nbsp;·&nbsp; '
    '<strong>3.</strong> Click <strong>&quot;Use this file&quot;</strong></div>',
    unsafe_allow_html=True,
)

_MB = 1024 * 1024
with st.expander("💡 Uploading a large file?", expanded=False):
    st.markdown(
        f"- CSV and Excel files can be up to **{MAX_UNCOMPRESSED_UPLOAD_BYTES // _MB} MB**.\n"
        f"- ZIP or GZ files can be up to **{MAX_COMPRESSED_UPLOAD_BYTES // _MB} MB** "
        f"(and up to {MAX_ARCHIVE_CONTENT_BYTES // _MB} MB once unzipped).\n"
        "- For big files, compress the CSV first: right-click it and choose "
        "**Send to → Compressed (zipped) folder**. This usually shrinks it by about 90%, "
        "so it uploads much faster and is less likely to time out."
    )

st.session_state.setdefault("raw_uploader_version", 0)

st.markdown(
    '<div class="lf-upload-label">📄 Lead file '
    '<span class="lf-upload-required">Required</span></div>',
    unsafe_allow_html=True,
)

raw_file_selected = st.file_uploader(
    "Drop your lead file here, or click Browse files",
    type=["csv", "xlsx", "xls", "zip", "gz"],
    key=f"raw_{st.session_state['raw_uploader_version']}",
    # Anything bigger is refused by validate_upload anyway; this stops it before a long upload.
    max_upload_size=MAX_COMPRESSED_UPLOAD_BYTES // _MB,
    help="The messy export you want cleaned — from a scraper, CRM, or list purchase. Supports CSV, XLSX, XLS, ZIP, or GZ.",
)
st.caption(
    f"Accepted: CSV, Excel (XLSX/XLS), ZIP or GZ · up to {MAX_UNCOMPRESSED_UPLOAD_BYTES // _MB} MB "
    f"({MAX_COMPRESSED_UPLOAD_BYTES // _MB} MB if compressed)"
)

# ---- Compare against (Master / Bounce / MQL / Unsub from the database) ----
# Shown right next to the uploader so the whole workflow is visible without scrolling.
st.markdown(
    '<div class="lf-upload-label">🚫 Exclude leads you don\'t want</div>',
    unsafe_allow_html=True,
)
st.caption("Any lead whose email is on a list you tick below is removed from your results.")
selected_master_list_ids = []
selected_bounce_list_ids = []
selected_mql_list_ids = []
selected_unsub_list_ids = []
if not db_is_ready():
    st.warning(
        "The lead database isn't connected, so saved lists can't be excluded right now. "
        "You can still clean your file — see the message at the top of the page."
    )
else:
    try:
        _cat_lists = {
            "master": db.get_master_lists(),
            "bounce": db.get_bounce_lists(),
            "mql": db.get_email_lists("mql"),
            "unsub": db.get_email_lists("unsub"),
        }
    except Exception as e:
        _cat_lists = {}
        st.warning("Couldn't load your saved lists, so they can't be excluded this time. Try refreshing the page.")
        st.caption(f"Technical details: {type(e).__name__}: {e}")

    def _category_picker(cat, label, help_text, count_col):
        """Checkbox for one category; when ticked, a multiselect of its lists (all by default)."""
        lists_df = _cat_lists.get(cat)
        if lists_df is None or lists_df.empty:
            st.checkbox(f"{label} (no lists yet)", value=False, disabled=True, key=f"cmp_{cat}_empty",
                        help=help_text + " Add a list on the Database page to use this.")
            return []
        labels = {int(r.id): f"{r.name} ({int(getattr(r, count_col)):,})" for r in lists_df.itertuples()}
        total = int(lists_df[count_col].sum())
        checked = st.checkbox(f"{label} — {total:,}", value=True, key=f"cmp_{cat}", help=help_text)
        if not checked:
            return []
        options = list(labels.keys())
        return st.multiselect(
            f"{label} lists",
            options=options,
            default=options,
            format_func=lambda i, m=labels: m.get(i, str(i)),
            key=f"sel_{cat}_lists",
            label_visibility="collapsed",
        )

    _cmp_cols = st.columns(4)
    with _cmp_cols[0]:
        selected_master_list_ids = _category_picker(
            "master", "🗂️ Master leads",
            "Leads already in your main database. Skips people you already have.", "contact_count")
    with _cmp_cols[1]:
        selected_bounce_list_ids = _category_picker(
            "bounce", "🚫 Bounced",
            "Emails that bounced before. Skipping them protects your sender reputation.", "email_count")
    with _cmp_cols[2]:
        selected_mql_list_ids = _category_picker(
            "mql", "🎯 MQL",
            "Marketing-qualified leads that are already being worked on.", "email_count")
    with _cmp_cols[3]:
        selected_unsub_list_ids = _category_picker(
            "unsub", "✋ Unsubscribed",
            "People who asked not to be contacted.", "email_count")
    st.caption("Tick a list to exclude it; pick specific lists in the box below it. "
               "Admins manage these lists on the **Database** page.")

if st.button("📤  Use this file", type="primary", key="go_use_file",
             help="Loads your file so you can check its columns before cleaning."):
    upload_error = validate_upload(raw_file_selected) if raw_file_selected is not None else None
    if raw_file_selected is None:
        st.warning("Choose a file first — drag it into the box above or click **Browse files**.")
    if upload_error:
        st.error(upload_error)
        st.session_state["active_raw_file"] = None
    else:
        st.session_state["active_raw_file"] = raw_file_selected

active_raw_file = st.session_state.get("active_raw_file")
if active_raw_file is not None:
    upload_error = validate_active_upload(active_raw_file)
    if upload_error:
        st.error(upload_error)
        st.stop()

if active_raw_file is not None:
    try:
        with st.spinner("Reading your file…"):
            df = load_file(active_raw_file)
    except Exception as e:
        theme.friendly_error(
            "We couldn't open your file",
            "Make sure it's a valid CSV, Excel (XLSX/XLS), ZIP or GZ file and that it isn't damaged "
            "or password-protected, then upload it again.",
            e,
        )
        st.stop()

    section_header(
        "02-Review", "Check your data",
        f"<strong>{html.escape(getattr(active_raw_file, 'name', 'Your file'))}</strong> — here are the first 10 rows "
        "so you can confirm it's the right file.",
    )
    summary_cols = st.columns(4)
    summary_cols[0].metric("Leads in file", f"{df.shape[0]:,}", help="Number of rows in your file, before cleaning.")
    summary_cols[1].metric("Columns", f"{df.shape[1]:,}", help="Number of columns found in your file.")

    st.dataframe(df.head(10), width="stretch")
    st.caption(f"Showing 10 of {df.shape[0]:,} rows · {df.shape[1]} columns")

    auto_mapping = auto_map_columns(df)

    section_header(
        "03-Options", "Match columns & choose options",
        "LeadFlow matched your file's columns automatically. Check them, then pick your cleaning options.",
    )
    st.caption(
        "Only **Email** is required. Fields shown as (none) weren't found in your file and will be left blank."
    )
    options = ["(none)"] + list(df.columns)
    mapping = {}
    map_cols = st.columns(4)
    fields_to_map = ["Full Name", "First Name", "Last Name", "Company", "Email", "Job Title", "Industry", "Location"]
    for i, field in enumerate(fields_to_map):
        default_col = auto_mapping.get(field, "(none)")
        field_missing = default_col == "(none)"
        default_index = options.index(default_col) if default_col in options else 0
        with map_cols[i % 4]:
            help_text = "No matching column found in this file" if field_missing else FIELD_HELP.get(field)
            selected = st.selectbox(
                field,
                options,
                index=default_index,
                key=f"map_{field}",
                disabled=field_missing,
                help=help_text,
            )
        if selected != "(none)":
            mapping[field] = selected

    if "Email" not in mapping:
        st.warning(
            "**No Email column selected.** LeadFlow needs an email address for every lead, so every row "
            "would be removed. Pick your email column above before cleaning."
        )

    with st.expander("🧭 Remove contacts based in India", expanded=True):
        st.caption(
            "Choose how LeadFlow spots India-based contacts. If too many leads are being removed, "
            "untick one option and clean again. Every removed contact is listed in the "
            "**Removed leads** tab after cleaning, with the reason it matched."
        )
        check_location = st.checkbox(
            "Check the Location column for Indian cities, states or 'India'", value=True,
            help="Uses the mapped Location field. Note: if your 'Location' column is really a sales "
                 "territory/region assignment rather than the contact's actual address, this can misfire.",
        )
        check_domain = st.checkbox(
            "Check for email addresses ending in .in", value=False,
            help="Flags any email address whose domain ends in the .in (India) TLD.",
        )

    with st.expander("🗂️ How do you want to download your leads?", expanded=True):
        st.caption(
            "You can always download the full campaign file. Tick the extra ways you'd like to split it — "
            "the split downloads appear in the Download step after cleaning."
        )
        split_by_location = st.checkbox(
            "Split by country", value=True,
            key="split_by_location",
            help="Groups the cleaned output by detected country and lets you download each country separately. "
                 "Requires a mapped Location column.",
        )
        split_by_field = st.checkbox(
            "Split by another field (Job Title, Industry, Company…)", value=False,
            key="split_by_field",
            help="Groups the cleaned output by any column you choose (Industry, Job Title, Company, ...). "
                 "Tick the groups you want and download them combined into one file.",
        )

    section_header(
        "04-Clean", "Clean your leads",
        "Removes leads with no email, India-based contacts, rows with garbled characters, "
        "duplicates, and anyone on the lists you ticked in step 1.",
    )

    # Conditional output goes into fixed container slots throughout this page: Streamlit keys
    # widgets and tabs by position, so an element that only appears on some reruns would
    # otherwise reset everything below it (e.g. bounce the Download tabs back to the first tab).
    _clean_clicked = st.button("🧹  Clean my leads", type="primary", key="go_clean",
                               help="Runs every cleaning step. Your original file is not changed.")
    _clean_area = st.container()
    if _clean_clicked:
        with _clean_area.status("Cleaning your leads…", expanded=False) as _clean_status:

            report = []
            start_count = len(df)
            report.append(f"Starting rows: {start_count:,}")

            # ---- STEP 1: Standardize ----
            std = pd.DataFrame()
            # Split Full Name if First/Last not directly available
            if "First Name" not in mapping and "Full Name" in mapping:
                full_series = df[mapping["Full Name"]].astype(str).str.strip()
                split_names = full_series.str.split(" ", n=1, expand=True)
                std["First Name"] = split_names[0].fillna("")
                std["Last Name"] = split_names[1].fillna("") if split_names.shape[1] > 1 else ""
                del full_series, split_names

            for field in FINAL_COLUMNS:
                if field in std.columns:
                    continue
                if field in mapping:
                    std[field] = df[mapping[field]].astype(str).str.strip()
                else:
                    std[field] = ""
            report.append(f"Step 1 - Standardized columns. Fields kept: {[c for c in FINAL_COLUMNS if c in mapping or c in std.columns]}")

            # ---- STEP 2: Remove blank email records ----
            _clean_status.update(label="Removing leads with no email address…")
            before = len(std)
            std["Email"] = std["Email"].astype(str).str.strip()
            std = std[(std["Email"] != "") & (std["Email"].str.lower() != "nan") & (std["Email"].str.lower() != "none")].reset_index(drop=True)
            report.append(f"Step 2 - Removed blank emails: {before - len(std):,} rows removed")

            # ---- STEP 3: Remove Indian contacts ----
            _clean_status.update(label="Removing contacts based in India…")
            before = len(std)
            indian_mask, matched_reason, matched_value = find_indian_contacts(
                std, "Location", "Email", check_location, check_domain
            )
            removed_indian_df = std[indian_mask].copy()
            removed_indian_df["Matched On"] = matched_reason[indian_mask]
            removed_indian_df["Matched Value"] = matched_value[indian_mask]
            st.session_state["removed_indian_df"] = removed_indian_df
            std = std[~indian_mask].reset_index(drop=True)
            report.append(f"Step 3 - Removed Indian contacts: {before - len(std):,} rows removed")
            del indian_mask, matched_reason, matched_value
            gc.collect()

            # ---- STEP 4: Separate special characters + clean non-email text ----
            _clean_status.update(label="Setting aside rows with garbled characters…")
            email_special_char_counts = std["Email"].astype(str).str.count(SPECIAL_CHARS_COUNT_PATTERN)
            total_special_chars_email = int(email_special_char_counts.sum())
            rows_with_special_chars_email = int((email_special_char_counts > 0).sum())

            field_masks = {}
            for col in FINAL_COLUMNS:
                series = std[col] if col in std.columns else pd.Series([""] * len(std), index=std.index)
                field_masks[col] = series.astype(str).str.contains(SPECIAL_CHARS_COUNT_PATTERN, regex=True, na=False)

            any_special_mask = pd.Series(False, index=std.index)
            for col in FINAL_COLUMNS:
                any_special_mask = any_special_mask | field_masks[col]

            email_special_mask = field_masks["Email"]

            if any_special_mask.any():
                removed_special_df = std[any_special_mask].copy()
                matched_flags = [np.where(field_masks[col][any_special_mask], col, "") for col in FINAL_COLUMNS if col in field_masks]
                if matched_flags:
                    combined_arr = np.column_stack(matched_flags)
                    removed_special_df["Matched Fields"] = [", ".join(filter(None, row)) for row in combined_arr]
                    del combined_arr, matched_flags
                else:
                    removed_special_df["Matched Fields"] = ""
                st.session_state["special_chars_removed_df"] = removed_special_df
            else:
                st.session_state["special_chars_removed_df"] = pd.DataFrame(columns=FINAL_COLUMNS + ["Matched Fields"])

            st.session_state["special_chars_email_df"] = std[email_special_mask].copy() if email_special_mask.any() else pd.DataFrame(columns=FINAL_COLUMNS)

            before = len(std)
            std = std[~any_special_mask].reset_index(drop=True)

            # Tidy whitespace in the remaining rows' non-email text. Every row with a special
            # character in any field was just moved to the audit file, so there are none
            # left to strip here.
            cleanable_columns = [c for c in FINAL_COLUMNS if c != "Email" and c in std.columns]
            for col in cleanable_columns:
                std[col] = std[col].str.replace(r"\s+", " ", regex=True).str.strip()

            report.append(
                f"Step 4 - Separated special-character rows into audit file: {before - len(std):,} rows removed from final output "
                f"({rows_with_special_chars_email:,} emails had special characters)"
                # f"{total_special_chars_email:,} special characters found in Email field total). "
            )
            del any_special_mask, field_masks, email_special_mask
            gc.collect()

            # ---- STEP 5: Remove duplicates within file (by Email) ----
            _clean_status.update(label="Removing duplicate leads…")
            before = len(std)
            std["__email_lower"] = std["Email"].str.lower()
            duplicate_count = int(std["__email_lower"].duplicated().sum())
            std = std.drop_duplicates(subset="__email_lower", keep="first").reset_index(drop=True)
            report.append(f"Step 5 - Removed in-file duplicates: {duplicate_count:,} duplicate rows removed")

            # One upload of the emails serves every list check in steps 6–7c; each check
            # only looks at the emails the earlier checks left (nothing is sent until needed).
            _probe = db.EmailProbe(std["__email_lower"].tolist())

            # ---- STEP 6: Remove records already in selected Master list(s) ----
            if db_is_ready() and selected_master_list_ids:
                try:
                    _clean_status.update(label="Checking against your Master leads…")
                    with st.spinner("Checking against your Master leads…"):
                        # Server-side lookup: only the emails that match come back.
                        master_emails = _probe.take_master(selected_master_list_ids)
                except Exception as e:
                    _probe.close()
                    _clean_status.update(label="Cleaning stopped", state="error", expanded=True)
                    theme.friendly_error(
                        "Couldn't check your Master leads",
                        "The lead database didn't respond, so cleaning stopped. Please try again in a moment, "
                        "or untick Master leads in step 1 to clean without it.",
                        e,
                    )
                    st.stop()
                before = len(std)
                std = std[~std["__email_lower"].isin(master_emails)].reset_index(drop=True)
                report.append(
                    f"Step 6 - Removed emails already in selected Master list(s): "
                    f"{before - len(std):,} rows removed ({len(master_emails):,} matches found)"
                )
                del master_emails
                gc.collect()
            elif not db_is_ready():
                report.append("Step 6 - Database not connected, Master suppression skipped")
            else:
                report.append("Step 6 - No Master list selected, step skipped")

            # ---- STEP 7: Remove bounced emails (from selected Bounce list(s)) ----
            if db_is_ready() and selected_bounce_list_ids:
                try:
                    _clean_status.update(label="Checking against your Bounced list…")
                    with st.spinner("Checking against your Bounced list…"):
                        bounce_emails = _probe.take("bounce", selected_bounce_list_ids)
                except Exception as e:
                    _probe.close()
                    _clean_status.update(label="Cleaning stopped", state="error", expanded=True)
                    theme.friendly_error(
                        "Couldn't check your Bounced list",
                        "The lead database didn't respond, so cleaning stopped. Please try again in a moment, "
                        "or untick Bounced in step 1 to clean without it.",
                        e,
                    )
                    st.stop()
                before = len(std)
                std = std[~std["__email_lower"].isin(bounce_emails)].reset_index(drop=True)
                report.append(
                    f"Step 7 - Removed bounced emails: "
                    f"{before - len(std):,} rows removed ({len(bounce_emails):,} matches found)"
                )
                del bounce_emails
                gc.collect()
            elif not db_is_ready():
                report.append("Step 7 - Database not connected, Bounce suppression skipped")
            else:
                report.append("Step 7 - No Bounce list selected, step skipped")

            # ---- STEP 7b / 7c: Remove MQL and Unsub emails (from selected lists) ----
            for _step, _cat, _label, _ids in (
                ("7b", "mql", "MQL", selected_mql_list_ids),
                ("7c", "unsub", "Unsub", selected_unsub_list_ids),
            ):
                if db_is_ready() and _ids:
                    try:
                        _clean_status.update(label=f"Checking against your {_label} list…")
                        with st.spinner(f"Checking against your {_label} list…"):
                            _hits = _probe.take(_cat, _ids)
                    except Exception as e:
                        _probe.close()
                        _clean_status.update(label="Cleaning stopped", state="error", expanded=True)
                        theme.friendly_error(
                            f"Couldn't check your {_label} list",
                            "The lead database didn't respond, so cleaning stopped. Please try again in a moment, "
                            f"or untick {_label} in step 1 to clean without it.",
                            e,
                        )
                        st.stop()
                    before = len(std)
                    std = std[~std["__email_lower"].isin(_hits)].reset_index(drop=True)
                    report.append(
                        f"Step {_step} - Removed {_label} emails: "
                        f"{before - len(std):,} rows removed ({len(_hits):,} matches found)"
                    )
                    del _hits
                    gc.collect()
                elif not db_is_ready():
                    report.append(f"Step {_step} - Database not connected, {_label} suppression skipped")
                else:
                    report.append(f"Step {_step} - No {_label} list selected, step skipped")

            _probe.close()
            std = std.drop(columns="__email_lower")

            # ---- STEP 8: Arrange final column sequence ----
            std = std[[c for c in FINAL_COLUMNS if c in std.columns]]

            # Drop Industry/Location columns entirely if never available and fully empty
            for optional_col in ["Industry", "Location"]:
                if optional_col not in mapping and optional_col in std.columns and (std[optional_col] == "").all():
                    std = std.drop(columns=optional_col)

            # ---- STEP 9: Final quality check ----
            before = len(std)
            valid_mask = (std["Email"] != "") & (std.ne("").any(axis=1))
            std = std[valid_mask].reset_index(drop=True)
            report.append(f"Step 9 - Final QC pass: removed {before - len(std):,} blank/empty rows")

            dup_check = int(std["Email"].str.lower().duplicated().sum())
            blank_email_check = int((std["Email"].astype(str).str.strip() == "").sum())
            report.append(f"Final QC - Duplicate emails remaining: {dup_check:,}")
            report.append(f"Final QC - Blank emails remaining: {blank_email_check:,}")
            report.append(f"Final row count: {len(std):,} (started at {start_count:,})")

            # ---- Country split (for download) ----
            _clean_status.update(label="Sorting leads by country…")
            if "Location" in std.columns:
                try:
                    with st.spinner("Loading country and city library…"):
                        country_ref = load_country_reference(str(COUNTRIES_JSON_PATH))
                    country_series = classify_countries_fast(std["Location"], country_ref)
                except Exception as e:
                    st.warning(f"Country split fallback: could not parse countries.json ({e}). All rows marked as Unknown.")
                    country_series = pd.Series(["Unknown"] * len(std), index=std.index)
            else:
                country_series = pd.Series(["Unknown"] * len(std), index=std.index)

            st.session_state["cleaned_df"] = std
            st.session_state["run_token"] = uuid.uuid4().hex
            # Master lists the output was already suppressed against (Step 6). If that covers
            # every list, the save-time dedup preview can skip its database lookup entirely.
            st.session_state["master_suppressed_list_ids"] = (
                sorted(int(i) for i in selected_master_list_ids) if db_is_ready() else []
            )
            st.session_state.pop("_dedup_preview", None)
            st.session_state["country_series"] = country_series
            st.session_state["country_counts"] = country_series.value_counts().to_dict()
            st.session_state["report"] = report
            st.session_state["metrics"] = {
                "indian_removed": len(st.session_state.get("removed_indian_df", [])),
                "duplicates_removed": duplicate_count,
                "special_char_rows": len(st.session_state.get("special_chars_removed_df", [])),
                "special_char_total": total_special_chars_email,
                "special_char_emails": rows_with_special_chars_email,
            }
            gc.collect()
            _clean_status.update(
                label=f"Cleaning complete — {len(std):,} leads are ready for your campaign",
                state="complete",
            )

    if "cleaned_df" in st.session_state:
        section_header(
            "05-Results", "Review your results",
            "What LeadFlow removed, and a preview of your clean leads.",
        )

        _ready = len(st.session_state["cleaned_df"])
        _ready_banner = st.container()
        if _ready:
            _ready_banner.success(f"**{_ready:,} leads are clean and ready for your campaign.**", icon="✅")

        metrics = st.session_state.get("metrics", {})
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🧹 Duplicates removed", f"{metrics.get('duplicates_removed', 0):,}",
                  help="Leads that appeared more than once in your file (same email). The first copy is kept.")
        m2.metric("🌏 India-based removed", f"{metrics.get('indian_removed', 0):,}",
                  help="Removed using the options you chose in step 3. See the Removed leads tab for details.")
        m3.metric("✉️ Odd-character emails", f"{metrics.get('special_char_emails', 0):,}",
                  help="Email addresses containing unusual symbols or letters. These rows are set aside for you to check.")
        m4.metric("🔣 Rows set aside", f"{metrics.get('special_char_rows', 0):,}",
                  help="Rows with garbled or special characters in any field. Download them from the Removed leads tab.")

        with st.expander("📋 Step-by-step report (what LeadFlow did)", expanded=False):
            for line in st.session_state["report"]:
                st.write("- " + line)

        st.subheader("Preview of your clean leads")
        with st.container():
            if _ready:
                st.caption("The first 50 rows, in the order they'll appear in your download.")
                st.dataframe(st.session_state["cleaned_df"].head(50), width="stretch")
                st.caption(f"{_ready:,} leads · {st.session_state['cleaned_df'].shape[1]} columns")
            else:
                theme.empty_state(
                    "📭", "No leads left in your campaign file",
                    "Either every lead was removed during cleaning, or you've already downloaded them all. "
                    "Upload a new file to start again.",
                )

        section_header(
            "06-Download", "Download your campaign",
            "Get the full campaign file, or split it by country or by another field.",
        )
        _dl_done = st.session_state.pop("_split_download_done", None)
        _dl_banner = st.container()
        if _dl_done:
            _dl_label, _dl_removed, _dl_left = _dl_done
            _dl_banner.success(
                f"**Download complete** — {_dl_removed:,} leads from **{_dl_label}** were downloaded "
                f"and removed from your Final Campaign file. {_dl_left:,} leads remain.",
                icon="✅",
            )

        split_by_location = st.session_state.get("split_by_location", True)
        split_by_field = st.session_state.get("split_by_field", False)

        tabs_to_show = ["📄 Full campaign file"]
        if split_by_location:
            tabs_to_show.append("🌍 By country")
        if split_by_field:
            tabs_to_show.append("🗂️ By field")
        tabs_to_show.append("🧾 Removed leads")

        all_tabs = st.tabs(tabs_to_show)
        tab_idx = 0
        tab_main = all_tabs[tab_idx]; tab_idx += 1
        tab_country = all_tabs[tab_idx] if split_by_location else None; tab_idx += (1 if split_by_location else 0)
        tab_field = all_tabs[tab_idx] if split_by_field else None; tab_idx += (1 if split_by_field else 0)
        tab_audit = all_tabs[tab_idx]

        with tab_main:
            final_df = st.session_state["cleaned_df"]
            is_large_dataset = len(final_df) > 100_000

            st.markdown(f"**⬇️ Full campaign file** — {len(final_df):,} leads")
            st.caption("Everything in your Final Campaign file, in one download. This does not remove any leads.")
            format_options = ["csv", "zip"] if is_large_dataset else ["xlsx", "csv", "zip"]
            out_format = st.radio(
                "File type",
                format_options,
                index=0,
                horizontal=True,
                help="XLSX opens in Excel. CSV works with most campaign tools. ZIP is a compressed CSV — "
                     "much smaller, so it downloads faster.",
                key="main_format",
            )

            dl_data, dl_name, dl_mime = make_download(final_df, out_format, "final_campaign_file")

            st.download_button(
                f"⬇️ Download campaign file ({out_format.upper()})",
                data=dl_data,
                file_name=dl_name,
                mime=dl_mime,
                type="primary",
                key="dl_main_file_btn"
            )
            st.caption("✔ Checked: no duplicate or blank emails — ready to upload into your campaign tool.")

            # Saving lives with the full campaign file it saves.
            section_header(
                "07-Save", "Save to your lead database",
                "Optional. Add these clean leads to a Master list so they're automatically skipped next time. "
                "Leads already saved in any Master list are never added twice.",
            )
            if not db_is_ready():
                st.warning(
                    "The lead database isn't connected, so leads can't be saved right now. "
                    "See the message at the top of the page."
                )
            else:
                final_df = st.session_state["cleaned_df"]
                try:
                    existing_master = db.get_master_lists()
                    existing_names = existing_master["name"].tolist() if not existing_master.empty else []
                except Exception as e:
                    existing_master = pd.DataFrame()
                    existing_names = []
                    st.warning("Couldn't load your Master lists. You can still create a new one.")
                    st.caption(f"Technical details: {type(e).__name__}: {e}")

                new_list_label = "➕ Create a new list…"
                save_choice = st.selectbox(
                    "Save into which Master list?",
                    [new_list_label] + existing_names,
                    key="save_master_choice",
                    help="Pick an existing list to add to, or create a new one.",
                )
                if save_choice == new_list_label:
                    target_name = st.text_input(
                        "New Master list name",
                        value=f"Cleaned {pd.Timestamp.now():%Y-%m-%d}",
                        key="save_master_newname",
                    )
                else:
                    target_name = save_choice

                clean_target = (target_name or "").strip()

                # --- Global dedup preview -------------------------------------------
                # Before saving, compute how many emails are truly new vs already stored
                # in ANY master list (not just the target list).
                try:
                    # Only recompute when the cleaned results change (new run) or after a save.
                    # The lookup runs server-side so only matching emails are transferred.
                    _dedup_key = st.session_state.get("run_token")
                    _dedup_cache = st.session_state.get("_dedup_preview")
                    if not _dedup_cache or _dedup_cache.get("key") != _dedup_key:
                        emails_in_final = final_df["Email"].astype(str).str.lower().str.strip()
                        _all_list_ids = set(int(i) for i in existing_master["id"].tolist()) if not existing_master.empty else set()
                        _suppressed_ids = st.session_state.get("master_suppressed_list_ids")
                        if _suppressed_ids is not None and _all_list_ids and _all_list_ids <= set(_suppressed_ids):
                            # Step 6 already removed every email present in any master list — nothing to look up.
                            new_mask = pd.Series(True, index=final_df.index)
                        else:
                            with st.spinner("Checking for existing emails in all master lists…"):
                                existing_emails = db.find_existing_master_emails(emails_in_final.tolist())
                            new_mask = ~emails_in_final.isin(existing_emails)
                        _dedup_cache = {"key": _dedup_key, "new_mask": new_mask}
                        st.session_state["_dedup_preview"] = _dedup_cache
                    new_mask = _dedup_cache["new_mask"]
                    new_count = int(new_mask.sum())
                    already_count = int(len(final_df) - new_count)

                    dedup_col1, dedup_col2 = st.columns(2)
                    dedup_col1.metric(
                        "✅ New leads to save",
                        f"{new_count:,}",
                        help="These emails are not yet in any master list and will be added.",
                    )
                    dedup_col2.metric(
                        "⏭️ Already saved (will be skipped)",
                        f"{already_count:,}",
                        help="These emails already exist in at least one master list and will be skipped.",
                    )

                    if new_count == 0:
                        st.info(
                            "ℹ️ All cleaned contacts already exist in your master lists. "
                            "Nothing new will be saved."
                        )
                    elif already_count > 0:
                        st.markdown(
                            f'<div class="lf-dedup-box warn">'
                            f'⚠️ <strong>{already_count:,}</strong> email(s) already stored across all master lists '
                            f'— only the <strong>{new_count:,}</strong> new contacts will be added to '
                            f'<strong>{clean_target or "—"}</strong>.'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f'<div class="lf-dedup-box">'
                            f'✅ All <strong>{new_count:,}</strong> contacts are new — '
                            f'none of them exist in any master list yet.'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                except Exception as e:
                    st.warning("Couldn't check which leads are already saved. Saving will still skip duplicates.")
                    st.caption(f"Technical details: {type(e).__name__}: {e}")
                    new_count = len(final_df)
                    new_mask = pd.Series([True] * len(final_df), index=final_df.index)

                if st.button(
                    f"💾 Save {new_count:,} new leads to Master",
                    type="primary",
                    key="save_to_master_btn",
                    disabled=(new_count == 0),
                ):
                    if not clean_target:
                        st.error("Please enter a name for the new Master list.")
                    else:
                        try:
                            # Only pass the truly new contacts (global dedup applied)
                            new_df = final_df[new_mask].copy()
                            with st.spinner(f"Saving {new_count:,} new contacts to '{clean_target}'…"):
                                records = cleaned_df_to_records(new_df)
                                list_id = db.get_or_create_master_list(clean_target)
                                written = db.upsert_master_contacts(
                                    list_id, records,
                                    upload=dict(
                                        file_name=f"{getattr(active_raw_file, 'name', 'Cleaned leads')} (cleaned in LeadFlow)",
                                        file_size_bytes=get_upload_size(active_raw_file) if active_raw_file is not None else None,
                                        rows_in_file=len(final_df), rows_skipped=len(final_df) - new_count,
                                        list_name=clean_target, uploaded_by=(auth.current_user() or {}).get("email"),
                                    ),
                                )
                            # Master data changed: refresh the dedup preview on the next rerun,
                            # and stop trusting the "already suppressed against all lists" shortcut.
                            st.session_state.pop("_dedup_preview", None)
                            st.session_state.pop("master_suppressed_list_ids", None)
                            st.success(
                                f"**Saved!** {written:,} new leads were added to Master list "
                                f"'{clean_target}'. They'll be skipped automatically in future runs.",
                                icon="✅",
                            )
                            st.balloons()
                        except Exception as e:
                            theme.friendly_error(
                                "Your leads couldn't be saved",
                                "Please try again. If it keeps happening, the lead database may be unavailable.",
                                e,
                            )

        if tab_country is not None:
            with tab_country:
                st.caption(
                    "Download one country's leads as a separate file. Countries are detected from the Location "
                    "column: **Unknown** means the location was blank, **Other** means no country was recognised."
                )
                country_series = st.session_state.get("country_series", pd.Series())
                country_counts = st.session_state.get("country_counts", {})
                final_df = st.session_state["cleaned_df"]

                if final_df.empty:
                    theme.empty_state("🎉", "No leads left to split", "Every lead has already been downloaded or removed.")
                elif country_series.empty or set(country_counts.keys()) == {"Unknown"}:
                    theme.empty_state(
                        "🌍", "No country information found",
                        "Pick a Location column in step 3 and clean your leads again to split them by country.",
                    )
                else:
                    counts_df = pd.DataFrame(
                        [{"Country": k, "Leads": v} for k, v in sorted(country_counts.items(), key=lambda x: -x[1])]
                    )
                    st.dataframe(counts_df, width="stretch", hide_index=True)

                    col_sel, col_dl = st.columns([2, 1])
                    available_countries = [k for k, v in sorted(country_counts.items(), key=lambda x: -x[1]) if v > 0]
                    with col_sel:
                        selected_country = st.selectbox(
                            "Choose a country", available_countries, key="selected_country_dl",
                            help="Countries are listed from most to fewest leads.",
                        )
                    if selected_country:
                        cnt = country_counts.get(selected_country, 0)
                        with col_sel:
                            st.markdown(
                                f'<div class="lf-note">⚠️ Downloading removes these {cnt:,} leads from your '
                                f'Final Campaign file, so they won\'t be included in later downloads.</div>',
                                unsafe_allow_html=True,
                            )
                        with col_dl:
                            country_df = final_df[country_series == selected_country]
                            safe_name = selected_country.lower().replace('/', '_').replace(' ', '_')
                            st.download_button(
                                f"⬇️ Download {selected_country} ({cnt:,} leads)",
                                data=csv_bytes(country_df),
                                file_name=f"final_campaign_file_{safe_name}.csv",
                                mime="text/csv",
                                type="primary",
                                key=f"dl_single_country_{safe_name}",
                                on_click=remove_downloaded_leads,
                                args=(country_df, (), selected_country),
                            )

        if tab_field is not None:
            with tab_field:
                final_df = st.session_state["cleaned_df"]
                st.caption(
                    "Split your leads by a field such as Job Title or Industry. Tick the groups you want — "
                    "they're downloaded together as one file."
                )

                # Scanning every column is slow on big files, so it's redone only when the
                # Final Campaign itself changes (new cleaning run or a split download).
                _cols_cache = st.session_state.get("_split_cols_cache")
                if not _cols_cache or _cols_cache["src"] is not final_df:
                    # Determine the best column to split by:
                    # Priority: mapped Industry column → any non-empty column in cleaned df
                    industry_col_in_df = "Industry" if (
                        "Industry" in final_df.columns
                        and not (final_df["Industry"].astype(str).str.strip() == "").all()
                    ) else None

                    # Collect all columns that have at least some non-blank values for user to pick from
                    # Exclude personal/identifier columns that don't make sense as split-by groups
                    _exclude_from_split = {"First Name", "Last Name", "Email"}
                    splittable_cols = [
                        c for c in final_df.columns
                        if c not in _exclude_from_split
                        and not (final_df[c].astype(str).str.strip() == "").all()
                    ]
                    _cols_cache = {"src": final_df, "industry": industry_col_in_df, "cols": splittable_cols}
                    st.session_state["_split_cols_cache"] = _cols_cache
                industry_col_in_df = _cols_cache["industry"]
                splittable_cols = list(_cols_cache["cols"])

                if final_df.empty:
                    theme.empty_state("🎉", "No leads left to split", "Every lead has already been downloaded or removed.")
                elif not splittable_cols:
                    theme.empty_state("🗂️", "Nothing to split by", "Your leads don't have any filled-in fields to group by.")
                else:
                    # Default split column: Industry if available, else first splittable col
                    default_split_col = industry_col_in_df or splittable_cols[0]
                    default_idx = splittable_cols.index(default_split_col) if default_split_col in splittable_cols else 0

                    split_col_choice = st.selectbox(
                        "Split by",
                        splittable_cols,
                        index=default_idx,
                        key="field_split_col_choice",
                        help="The field used to group your leads — for example Job Title or Industry.",
                    )

                    group_series = final_df[split_col_choice].astype(str).str.strip()
                    group_series = group_series.replace("", "Unknown").replace("nan", "Unknown")
                    group_counts = group_series.value_counts().to_dict()
                    ordered_groups = [k for k, v in sorted(group_counts.items(), key=lambda x: -x[1]) if v > 0]
                    safe_col = split_col_choice.lower().replace(" ", "_")

                    st.caption(
                        f"**{len(ordered_groups):,}** different {split_col_choice} values found. "
                        "Leads with this field left blank are grouped under **Unknown**."
                    )

                    # Search box: type part of a value (e.g. "Software") to narrow the table.
                    # Selections are remembered across searches so you can pick from several.
                    # The remembered set (sel_key) is the single source of truth for what is
                    # selected; the table and "Select all shown" only change it.
                    sel_key = f"split_selected_{safe_col}"
                    all_key = f"split_select_all_{safe_col}"
                    ver_key = f"split_editor_ver_{safe_col}"

                    def _on_group_search_change(all_key=all_key):
                        # A new search shows different groups, so untick "Select all shown"
                        # (it only ever applied to the groups shown when it was ticked).
                        # Remembered selections are kept.
                        st.session_state[all_key] = False

                    search_col, all_col, clear_col = st.columns([3, 1, 1], vertical_alignment="bottom")
                    group_search = search_col.text_input(
                        f"🔎 Search {split_col_choice}",
                        key=f"split_group_search_{safe_col}",
                        placeholder="Type to find a value, e.g. Software, Healthcare, Finance, SaaS…",
                        on_change=_on_group_search_change,
                    ).strip().lower()
                    visible_groups = (
                        [g for g in ordered_groups if group_search in g.lower()] if group_search else ordered_groups
                    )

                    def _on_select_all_toggle(sel_key=sel_key, all_key=all_key, shown=tuple(visible_groups)):
                        # The checkbox is authoritative when toggled: ticking selects every
                        # shown group, unticking clears every shown group. Groups hidden by
                        # the current search keep their state.
                        current = set(st.session_state.get(sel_key, ()))
                        if st.session_state.get(all_key):
                            current |= set(shown)
                        else:
                            current -= set(shown)
                        st.session_state[sel_key] = current

                    select_all_groups = all_col.checkbox(
                        "Select all shown",
                        value=False,
                        key=all_key,
                        on_change=_on_select_all_toggle,
                        help="Ticks every group in the list below (only those matching your search).",
                    )

                    def _on_clear_selection(sel_key=sel_key, all_key=all_key, ver_key=ver_key):
                        st.session_state[sel_key] = set()
                        st.session_state[all_key] = False
                        # New editor key so the table doesn't re-apply its old ticks.
                        st.session_state[ver_key] = st.session_state.get(ver_key, 0) + 1

                    clear_col.button(
                        "Clear all",
                        key=f"reset_split_{safe_col}",
                        on_click=_on_clear_selection,
                        disabled=not st.session_state.get(sel_key),
                        help="Unticks every group, including ones hidden by your search.",
                        width="stretch",
                    )
                    if group_search:
                        st.caption(f"Showing {len(visible_groups):,} of {len(ordered_groups):,} groups matching “{group_search}”.")

                    selected_set = set(st.session_state.get(sel_key, ()))
                    groups_table = pd.DataFrame(
                        [{"Select": k in selected_set, "Group": k, "Rows": group_counts[k]}
                         for k in visible_groups]
                    )
                    if groups_table.empty:
                        theme.empty_state("🔎", "No matching groups", f"Nothing matches “{html.escape(group_search)}”. Try a different search.")
                        edited_groups = groups_table
                    else:
                        # Key includes the column, select-all state, search and clear count so the editor resets when any changes.
                        edited_groups = st.data_editor(
                            groups_table,
                            column_config={
                                "Select": st.column_config.CheckboxColumn("Select", default=False),
                                "Group": st.column_config.TextColumn(split_col_choice),
                                "Rows": st.column_config.NumberColumn("Leads", format="%d"),
                            },
                            disabled=["Group", "Rows"],
                            hide_index=True,
                            width="stretch",
                            key=(f"split_group_editor_{safe_col}_{st.session_state.get(ver_key, 0)}_"
                                 f"{int(select_all_groups)}_{hash(group_search) & 0xFFFFFFFF}"),
                        )

                    if not edited_groups.empty:
                        visible_selected = set(
                            edited_groups.loc[edited_groups["Select"].fillna(False).astype(bool), "Group"].tolist()
                        )
                    else:
                        visible_selected = set()
                    selected_set = (selected_set - set(visible_groups)) | visible_selected
                    st.session_state[sel_key] = selected_set
                    selected_groups = [g for g in ordered_groups if g in selected_set]

                    if not selected_groups:
                        st.info("Tick one or more groups above to build your download.", icon="👆")
                    else:
                        combined_mask = group_series.isin(selected_groups)
                        combined_rows = int(combined_mask.sum())
                        group_order = {g: i for i, g in enumerate(ordered_groups)}

                        combined_df = final_df[combined_mask]

                        def _build_combined(df=combined_df, order=group_order, gs=group_series[combined_mask]):
                            # Keep rows of the same group together, in the order the groups are listed.
                            # Runs only when the download button is clicked.
                            df = df.assign(__grp_order=gs.map(order))
                            df = df.sort_values("__grp_order", kind="stable").drop(columns="__grp_order")
                            return df.to_csv(index=False).encode("utf-8")

                        sel_col1, sel_col2 = st.columns([2, 1])
                        with sel_col1:
                            st.write(
                                f"**{len(selected_groups):,} of {len(ordered_groups):,} groups selected** · "
                                f"**{combined_rows:,} leads** "
                                f"({', '.join(selected_groups[:5])}{'…' if len(selected_groups) > 5 else ''})"
                            )
                            st.markdown(
                                f'<div class="lf-note">⚠️ Downloading removes these {combined_rows:,} leads from your '
                                f'Final Campaign file, so they won\'t be included in later downloads.</div>',
                                unsafe_allow_html=True,
                            )
                        with sel_col2:
                            _grp_label = (selected_groups[0] if len(selected_groups) == 1
                                          else f"{len(selected_groups):,} {split_col_choice} groups")
                            st.download_button(
                                f"⬇️ Download selected ({combined_rows:,} leads)",
                                data=_build_combined,
                                file_name=f"split_{safe_col}_selected_groups.csv",
                                mime="text/csv",
                                type="primary",
                                key=f"dl_combined_split_{safe_col}",
                                on_click=remove_downloaded_leads,
                                args=(combined_df, (all_key,), _grp_label),
                            )

        with tab_audit:
            st.caption(
                "Leads LeadFlow removed or set aside while cleaning — download them if you want to double-check. "
                "None of these are in your campaign file."
            )

            removed_indian_df = st.session_state.get("removed_indian_df", pd.DataFrame())
            st.write(f"**India-based contacts removed:** {len(removed_indian_df):,}")
            if len(removed_indian_df) > 0:
                st.dataframe(removed_indian_df.head(20), width="stretch")
                st.download_button(
                    "⬇️ Download removed Indian contacts (full list)",
                    data=csv_bytes(removed_indian_df),
                    file_name="removed_indian_contacts.csv",
                    mime="text/csv",
                    key="dl_indian_audit",
                    type="primary",
                )
                st.caption("The 'Matched On' and 'Matched Value' columns show why each contact was removed.")

            st.divider()

            special_chars_df = st.session_state.get("special_chars_removed_df", pd.DataFrame())
            st.write(f"**Rows set aside because of odd or garbled characters:** {len(special_chars_df):,}")
            if len(special_chars_df) > 0:
                st.dataframe(special_chars_df.head(20), width="stretch")
                st.download_button(
                    "⬇️ Download uncleaned special-characters file (full list)",
                    data=csv_bytes(special_chars_df),
                    file_name="special_characters_separated_uncleaned.csv",
                    mime="text/csv",
                    key="dl_specialchars_audit",
                    type="primary",
                )
                st.caption("This file contains the rows exactly as they were in your upload, odd characters included.")

                # Build cleaned version: strip special chars from all non-email columns.
                # Cached against the audit frame, which only changes on a new cleaning run.
                _audit_cache = st.session_state.get("_special_chars_cleaned_cache")
                if not _audit_cache or _audit_cache["src"] is not special_chars_df:
                    _audit_cleanable_cols = [c for c in FINAL_COLUMNS if c != "Email" and c in special_chars_df.columns]
                    special_chars_cleaned_df = special_chars_df.drop(
                        columns=[c for c in ["Matched Fields"] if c in special_chars_df.columns],
                        errors="ignore",
                    ).copy()
                    for _col in _audit_cleanable_cols:
                        special_chars_cleaned_df[_col] = (
                            special_chars_cleaned_df[_col]
                            .astype(str)
                            .str.replace(SPECIAL_CHARS_COUNT_PATTERN, "", regex=True)
                            .str.replace(r"\s+", " ", regex=True)
                            .str.strip()
                        )
                    _audit_cache = {"src": special_chars_df, "out": special_chars_cleaned_df}
                    st.session_state["_special_chars_cleaned_cache"] = _audit_cache
                special_chars_cleaned_df = _audit_cache["out"]

                st.markdown("**Cleaned preview** — same rows after removing special characters from non-email fields:")
                st.dataframe(special_chars_cleaned_df.head(20), width="stretch")
                st.download_button(
                    "⬇️ Download cleaned special-characters file (full list)",
                    data=csv_bytes(special_chars_cleaned_df),
                    file_name="special_characters_separated_cleaned.csv",
                    mime="text/csv",
                    key="dl_specialchars_cleaned_audit",
                    type="primary",
                )
                st.caption("Email column is preserved as-is. Only non-email fields have had special characters stripped.")

            st.divider()

            email_special_df = st.session_state.get("special_chars_email_df", pd.DataFrame())
            st.write(f"**Rows where Email specifically contains special characters (uncleaned):** {len(email_special_df):,} rows")
            if len(email_special_df) > 0:
                st.dataframe(email_special_df.head(20), width="stretch")
                st.download_button(
                    "⬇️ Download email-special-characters file (full list)",
                    data=csv_bytes(email_special_df),
                    file_name="email_special_characters_separated.csv",
                    mime="text/csv",
                    key="dl_email_specialchars_audit",
                    type="primary",
                )

else:
    theme.empty_state(
        "📂", "No leads uploaded yet",
        "Upload a CSV or Excel file above, then click <strong>Use this file</strong> to get started.",
    )

theme.workflow_steps(_workflow_step(), _stepper)
