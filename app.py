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
8. Arrange final column sequence
9. Final quality check + summary report
10. Optionally save the cleaned contacts back into a Master list (database)

Master/Bounce suppression data lives in PostgreSQL (see db.py) and is managed on
the "Manage Suppression Database" page — it is no longer uploaded on each run.
"""

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
        "⚠️ **Can't reach the suppression database.** Master/Bounce suppression "
        "and saving cleaned contacts are unavailable until it's connected. "
        "You can still clean files — those steps will simply be skipped."
    )
    with st.expander("How to fix this", expanded=False):
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

if not db_is_ready():
    render_db_error_banner()


# Use shared section_header from theme module
def section_header(number, title):
    theme.section_header(number, title)



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

    return {
        "country_name_lookup": country_name_lookup,
        "alias_lookup": alias_lookup,
        "city_to_countries": city_to_countries,
        "city_alias_lookup": city_alias_lookup,
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
            for city_key, countries_set in city_to_countries.items():
                if len(city_key) < 4:
                    continue
                if re.search(rf"(?<![a-z0-9]){re.escape(city_key)}(?![a-z0-9])", part):
                    matched_countries = countries_set
                    break
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
                        return pd.read_excel(inner_f)

        elif filename.endswith((".gz", ".gzip")):
            try:
                return pd.read_csv(file, compression="gzip", encoding="utf-8", low_memory=False)
            except (UnicodeDecodeError, UnicodeError):
                file.seek(0)
                return pd.read_csv(file, compression="gzip", encoding="latin1", encoding_errors="replace", low_memory=False)

        elif filename.endswith(".csv"):
            encodings_to_try = ["utf-8", "utf-8-sig", "cp1252", "latin1"]
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
            return pd.read_excel(file, engine="openpyxl")

        elif filename.endswith(".xls"):
            file.seek(0)
            return pd.read_excel(file, engine="xlrd")

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
    return st.session_state[cache_key]


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
        def _build():
            buf = io.BytesIO()
            df.to_excel(buf, index=False, engine="openpyxl")
            return buf.getvalue()
        return _build, f"{base_name}.xlsx", XLSX_MIME
    return csv_bytes(df), f"{base_name}.csv", "text/csv"


# ---------------- FILE UPLOADS ----------------
section_header("01-Upload the Files", "Upload")
st.markdown(
    '<div class="upload-card">📁 Drag and drop your raw lead file below, then click '
    '<strong>&quot;Use Selected File&quot;</strong> to continue.</div>',
    unsafe_allow_html=True,
)

with st.expander("💡 Large-file upload tip", expanded=False):
    st.info(
        "💡 **Important for 500k+ Rows on Cloud:**\n\n"
        "Cloud hosts (Streamlit Cloud) enforce a **60–90 second network timeout** per upload request. "
        "Uploading an uncompressed 100MB+ CSV over standard broadband takes 3–5 minutes and triggers a timeout (`ClientDisconnect`).\n\n"
        "👉 **Recommended:** Right-click your CSV and choose **Send to → Compressed (zipped) folder** (or `.csv.gz`). "
        "This reduces file size by **90%** (e.g. from 150MB down to ~15MB), uploading in **under 15 seconds** with zero timeouts!"
    )

st.session_state.setdefault("raw_uploader_version", 0)

st.markdown(
    '<div class="lf-upload-label">📄 Raw Lead File '
    '<span class="lf-upload-required">Required</span></div>',
    unsafe_allow_html=True,
)

raw_file_selected = st.file_uploader(
    "Drag and drop CSV/XLSX",
    type=["csv", "xlsx", "xls", "zip", "gz"],
    key=f"raw_{st.session_state['raw_uploader_version']}",
    help="The messy export you want cleaned — from a scraper, CRM, or list purchase. Supports CSV, XLSX, XLS, ZIP, or GZ.",
)

st.caption(
    "🗄️ Master & Bounce suppression now come from your database. Pick which lists "
    "to suppress against in **Step 03** below, and manage them on the "
    "**Manage Suppression Database** page (left sidebar)."
)

if st.button("📤  Use Selected File", type="primary"):
    upload_error = validate_upload(raw_file_selected) if raw_file_selected is not None else None
    if upload_error:
        st.error(upload_error)
        st.session_state["active_raw_file"] = None
    else:
        st.session_state["active_raw_file"] = raw_file_selected

active_raw_file = st.session_state.get("active_raw_file")
if active_raw_file is not None:
    upload_error = validate_upload(active_raw_file)
    if upload_error:
        st.error(upload_error)
        st.stop()

if active_raw_file is not None:
    try:
        with st.spinner("Loading raw lead file..."):
            df = load_file(active_raw_file)
    except Exception as e:
        st.error(f"Could not read the uploaded raw lead file: {e}")
        st.info("Please make sure the file is a valid CSV, XLSX, XLS, or ZIP/GZ file and isn't corrupted.")
        st.stop()

    section_header("02-Preview Selected Raw File Data", "Review Data")
    summary_cols = st.columns(4)
    summary_cols[0].metric("Rows", f"{df.shape[0]:,}")
    summary_cols[1].metric("Columns", f"{df.shape[1]:,}")

    st.caption("🔍 Quick preview of detected data before mapping and processing.")
    st.dataframe(df.head(10), width="stretch")
    st.caption(f"{df.shape[0]:,} rows x {df.shape[1]} columns.")

    auto_mapping = auto_map_columns(df)

    section_header("03- Map Columns", "Configure")
    st.write(
        "Confirm column mapping and filtering options before processing. "
        "All cleaning logic remains exactly the same."
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
        st.warning("No Email column is mapped. Every row will be treated as blank-email and removed — double-check your mapping above.")

    with st.expander("🧭 Indian Contact Filtering", expanded=True):
        st.caption(
            "If Step 3 is removing rows that shouldn't be flagged, check which signal is causing it "
            "by toggling these off one at a time and re-running. Every removed row is also available "
            "as a downloadable audit file after processing, showing exactly what matched."
        )
        check_location = st.checkbox(
            "Match by Location text (city/state/country names)", value=True,
            help="Uses the mapped Location field. Note: if your 'Location' column is really a sales "
                 "territory/region assignment rather than the contact's actual address, this can misfire.",
        )
        check_domain = st.checkbox(
            "Match by email domain ending in .in", value=False,
            help="Flags any email address whose domain ends in the .in (India) TLD.",
        )

    with st.expander("🗃️ Output Organization", expanded=True):
        st.caption(
            "Choose how you want the final cleaned data split when downloading. "
            "Splits are generated on-demand in the Download step — check what you need before running the pipeline."
        )
        split_by_location = st.checkbox(
            "Split output by Location (country)", value=True,
            key="split_by_location",
            help="Groups the cleaned output by detected country and lets you download each country separately. "
                 "Requires a mapped Location column.",
        )
        split_by_field = st.checkbox(
            "Split output by field (Industry, Job Title, Company, etc.)", value=False,
            key="split_by_field",
            help="Groups the cleaned output by any column you choose (Industry, Job Title, Company, ...). "
                 "Tick the groups you want and download them combined into one file.",
        )

    selected_master_list_ids = []
    selected_bounce_list_ids = []
    with st.expander("🗄️ Suppression lists (from your database)", expanded=True):
        if not db_is_ready():
            st.warning(
                "Database not connected — Master/Bounce suppression will be skipped. "
                "See the banner at the top of the page to reconnect."
            )
        else:
            st.caption(
                "Choose which stored lists to suppress against. Import or manage lists on the "
                "**Manage Suppression Database** page (left sidebar). All lists are selected by default."
            )
            try:
                master_lists_df = db.get_master_lists()
                bounce_lists_df = db.get_bounce_lists()
            except Exception as e:
                master_lists_df = pd.DataFrame()
                bounce_lists_df = pd.DataFrame()
                st.warning(f"Could not load lists from the database: {e}")

            sup_c1, sup_c2 = st.columns(2)
            with sup_c1:
                if master_lists_df is not None and not master_lists_df.empty:
                    m_labels = {
                        int(r.id): f"{r.name} ({int(r.contact_count):,})"
                        for r in master_lists_df.itertuples()
                    }
                    m_options = list(m_labels.keys())
                    selected_master_list_ids = st.multiselect(
                        "🗂️ Master lists — remove contacts you already have",
                        options=m_options,
                        default=m_options,
                        format_func=lambda i: m_labels.get(i, str(i)),
                        key="sel_master_lists",
                    )
                else:
                    st.info("No Master lists yet. Add one on the Manage Suppression Database page.")
            with sup_c2:
                if bounce_lists_df is not None and not bounce_lists_df.empty:
                    b_labels = {
                        int(r.id): f"{r.name} ({int(r.email_count):,})"
                        for r in bounce_lists_df.itertuples()
                    }
                    b_options = list(b_labels.keys())
                    selected_bounce_list_ids = st.multiselect(
                        "🚫 Bounce lists — remove previously bounced emails",
                        options=b_options,
                        default=b_options,
                        format_func=lambda i: b_labels.get(i, str(i)),
                        key="sel_bounce_lists",
                    )
                else:
                    st.info("No Bounce lists yet. Add one on the Manage Suppression Database page.")

    section_header("04-Process The Data Files", "Run Processing")
    st.caption("▶️ Runs the full cleaning workflow and prepares campaign-ready output.")

    if st.button("▶️  Run Cleaning Pipeline", type="primary"):
        with st.spinner("Processing — running high-performance cleaning pipeline..."):
            
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
            before = len(std)
            std["Email"] = std["Email"].astype(str).str.strip()
            std = std[(std["Email"] != "") & (std["Email"].str.lower() != "nan") & (std["Email"].str.lower() != "none")].reset_index(drop=True)
            report.append(f"Step 2 - Removed blank emails: {before - len(std):,} rows removed")

            # ---- STEP 3: Remove Indian contacts ----
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

            # Fast vectorized C-regex cleaning of non-email text in remaining rows
            cleanable_columns = [c for c in FINAL_COLUMNS if c != "Email" and c in std.columns]
            rows_changed_after_clean = 0
            for col in cleanable_columns:
                has_special = std[col].str.contains(SPECIAL_CHARS_COUNT_PATTERN, regex=True, na=False)
                if has_special.any():
                    rows_changed_after_clean += int(has_special.sum())
                std[col] = std[col].str.replace(SPECIAL_CHARS_COUNT_PATTERN, "", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()

            report.append(
                f"Step 4 - Separated special-character rows into audit file: {before - len(std):,} rows removed from final output "
                f"({rows_with_special_chars_email:,} emails had special characters)"
                # f"{total_special_chars_email:,} special characters found in Email field total). "
                # f"Then cleaned non-email text fields in remaining rows: {rows_changed_after_clean:,} rows cleaned"
            )
            del any_special_mask, field_masks, email_special_mask
            gc.collect()

            # ---- STEP 5: Remove duplicates within file (by Email) ----
            before = len(std)
            std["__email_lower"] = std["Email"].str.lower()
            duplicate_count = int(std["__email_lower"].duplicated().sum())
            std = std.drop_duplicates(subset="__email_lower", keep="first").reset_index(drop=True)
            report.append(f"Step 5 - Removed in-file duplicates: {duplicate_count:,} duplicate rows removed")

            # ---- STEP 6: Remove records already in selected Master list(s) ----
            if db_is_ready() and selected_master_list_ids:
                try:
                    with st.spinner("Checking emails against the selected Master list(s) in the database..."):
                        # Server-side lookup: only the emails that match come back.
                        master_emails = db.find_existing_master_emails(
                            std["__email_lower"].tolist(), selected_master_list_ids
                        )
                except Exception as e:
                    st.error(f"Could not check Master emails in the database: {e}")
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
                    with st.spinner("Checking emails against the selected Bounce list(s) in the database..."):
                        bounce_emails = db.find_existing_bounce_emails(
                            std["__email_lower"].tolist(), selected_bounce_list_ids
                        )
                except Exception as e:
                    st.error(f"Could not check Bounce emails in the database: {e}")
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
            if "Location" in std.columns:
                try:
                    with st.spinner("Loading country and city library..."):
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
            st.session_state.pop("_compare_cache", None)
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

    if "cleaned_df" in st.session_state:
        section_header("05-Preview Cleaned Data Results", "Review Results")

        metrics = st.session_state.get("metrics", {})
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🧹 Duplicate emails removed", f"{metrics.get('duplicates_removed', 0):,}")
        m2.metric("🌏 Indian contacts removed", f"{metrics.get('indian_removed', 0):,}")
        m3.metric("✉️ Emails with special characters", f"{metrics.get('special_char_emails', 0):,}")
        m4.metric("🔣 Rows containing special characters", f"{metrics.get('special_char_rows', 0):,}")

        with st.expander("📋 Processing report (what happened at each step)", expanded=True):
            for line in st.session_state["report"]:
                st.write("- " + line)

        st.subheader("✅ Final cleaned data preview")
        st.caption("This is what your downloaded file will contain, in final campaign order.")
        st.dataframe(st.session_state["cleaned_df"].head(50), width="stretch")
        st.caption(f"{st.session_state['cleaned_df'].shape[0]:,} rows x {st.session_state['cleaned_df'].shape[1]} columns")

        section_header("06-Download the Cleaned Data", "Download")

        split_by_location = st.session_state.get("split_by_location", True)
        split_by_field = st.session_state.get("split_by_field", False)

        tabs_to_show = ["📄 Final campaign file"]
        if split_by_location:
            tabs_to_show.append("🌍 Split by country")
        if split_by_field:
            tabs_to_show.append("🗂️ Split by field")
        tabs_to_show.append("🧾 Audit files (removed rows)")

        all_tabs = st.tabs(tabs_to_show)
        tab_idx = 0
        tab_main = all_tabs[tab_idx]; tab_idx += 1
        tab_country = all_tabs[tab_idx] if split_by_location else None; tab_idx += (1 if split_by_location else 0)
        tab_field = all_tabs[tab_idx] if split_by_field else None; tab_idx += (1 if split_by_field else 0)
        tab_audit = all_tabs[tab_idx]

        with tab_main:
            final_df = st.session_state["cleaned_df"]
            is_large_dataset = len(final_df) > 100_000

            # Left: download the final file. Right: upload a file to compare against and
            # remove overlapping emails — kept side by side so the two options read as a pair.
            main_dl_col, main_cmp_col = st.columns(2, gap="large")

            with main_dl_col:
                st.markdown("**⬇️ Download final campaign file**")
                format_options = ["csv", "zip"] if is_large_dataset else ["xlsx", "csv", "zip"]
                out_format = st.radio(
                    "Download format",
                    format_options,
                    index=0,
                    horizontal=True,
                    help="CSV is standard for campaign tools; ZIP compresses the CSV by ~90% for instant download.",
                    key="main_format",
                )

                dl_data, dl_name, dl_mime = make_download(final_df, out_format, "final_campaign_file")

                st.download_button(
                    f"⬇️ Download final campaign file ({out_format.upper()})",
                    data=dl_data,
                    file_name=dl_name,
                    mime=dl_mime,
                    type="primary",
                    key="dl_main_file_btn"
                )
                st.caption("This file has already passed the final quality check — no duplicate or blank emails, ready to upload into your campaign tool.")

            with main_cmp_col:
                st.markdown("**🔍 Compare with another file & remove duplicates**")
                compare_file = st.file_uploader(
                    "Upload a file to compare against",
                    type=["csv", "xlsx", "xls", "zip", "gz"],
                    key="compare_file_uploader",
                    help="Matching is done by email address (case-insensitive).",
                )
                st.caption(
                    "Upload a downloaded campaign to remove duplicates from this final file. "
                )

                if compare_file is not None:
                    try:
                        validate_upload(compare_file)
                        compare_df = load_file(compare_file)
                    except Exception as e:
                        compare_df = None
                        st.error(f"Could not read the comparison file: {e}")

                    if compare_df is not None and len(compare_df.columns) > 0:
                        compare_cols = list(compare_df.columns)
                        auto_email_col = auto_map_columns(compare_df).get("Email")
                        compare_email_col = auto_email_col if auto_email_col in compare_cols else compare_cols[0]

                        # The overlap only changes when the results, the uploaded file, or the
                        # detected column change — so compute it once and reuse across reruns.
                        cmp_key = (
                            st.session_state.get("run_token"),
                            getattr(compare_file, "name", ""),
                            getattr(compare_file, "size", 0),
                            compare_email_col,
                        )
                        cmp_cache = st.session_state.get("_compare_cache")
                        if not cmp_cache or cmp_cache.get("key") != cmp_key:
                            compare_emails = (
                                compare_df[compare_email_col].dropna().astype(str).str.strip().str.lower()
                            )
                            compare_emails = compare_emails[(compare_emails != "") & (compare_emails != "nan")]
                            compare_email_set = set(compare_emails.tolist())
                            final_emails_lower = final_df["Email"].astype(str).str.strip().str.lower()
                            cmp_cache = {
                                "key": cmp_key,
                                "dup_mask": final_emails_lower.isin(compare_email_set),
                            }
                            st.session_state["_compare_cache"] = cmp_cache
                        dup_mask = cmp_cache["dup_mask"]
                        unique_df = final_df[~dup_mask].reset_index(drop=True)
                        dup_df = final_df[dup_mask].reset_index(drop=True)

                        st.metric("♻️ Duplicates found in uploaded file", f"{len(dup_df):,}")
                        st.caption(f"Download Unique File without duplicates.")

                        uniq_data, uniq_name, uniq_mime = make_download(unique_df, out_format, "final_campaign_file_unique")
                        st.download_button(
                            f"⬇️ Download unique file ({out_format.upper()})",
                            data=uniq_data,
                            file_name=uniq_name,
                            mime=uniq_mime,
                            type="primary",
                            key="dl_unique_file_btn",
                        )
                    elif compare_df is not None:
                        st.warning("The uploaded file has no columns to compare.")

        if tab_country is not None:
            with tab_country:
                st.caption(
                    "Split based on [data/countries.json](data/countries.json) country and city matching against Location. "
                    "'Other' means a location was present but no country/city keyword matched; 'Unknown' means Location was blank."
                )
                country_series = st.session_state.get("country_series", pd.Series())
                country_counts = st.session_state.get("country_counts", {})
                final_df = st.session_state["cleaned_df"]

                if country_series.empty or set(country_counts.keys()) == {"Unknown"}:
                    st.info("No Location data was available to split by — map a Location column and re-run to use this.")
                else:
                    counts_df = pd.DataFrame(
                        [{"Group": k, "Rows": v} for k, v in sorted(country_counts.items(), key=lambda x: -x[1])]
                    )
                    st.dataframe(counts_df, width="stretch", hide_index=True)

                    col_sel, col_dl = st.columns([2, 1])
                    available_countries = [k for k, v in sorted(country_counts.items(), key=lambda x: -x[1]) if v > 0]
                    with col_sel:
                        selected_country = st.selectbox("Select Country to Download", available_countries, key="selected_country_dl")
                    with col_dl:
                        if selected_country:
                            cnt = country_counts.get(selected_country, 0)
                            country_df = final_df[country_series == selected_country]
                            safe_name = selected_country.lower().replace('/', '_').replace(' ', '_')
                            st.download_button(
                                f"⬇️ Download {selected_country} ({cnt:,} rows)",
                                data=csv_bytes(country_df),
                                file_name=f"final_campaign_file_{safe_name}.csv",
                                mime="text/csv",
                                type="primary",
                                key=f"dl_single_country_{safe_name}",
                            )

        if tab_field is not None:
            with tab_field:
                final_df = st.session_state["cleaned_df"]
                st.caption(
                    "Split the final campaign file by any field — Industry, Job Title, Company, Location, etc. "
                    "Tick the groups you want and download them together as one file."
                )

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

                if not splittable_cols:
                    st.info("No data columns available to split by — re-run the pipeline first.")
                else:
                    # Default split column: Industry if available, else first splittable col
                    default_split_col = industry_col_in_df or splittable_cols[0]
                    default_idx = splittable_cols.index(default_split_col) if default_split_col in splittable_cols else 0

                    split_col_choice = st.selectbox(
                        "Field to split by",
                        splittable_cols,
                        index=default_idx,
                        key="field_split_col_choice",
                        help="Choose which column to group the data by. Defaults to Industry if available; "
                             "pick Job Title, Company, or any other column as needed.",
                    )

                    group_series = final_df[split_col_choice].astype(str).str.strip()
                    group_series = group_series.replace("", "Unknown").replace("nan", "Unknown")
                    group_counts = group_series.value_counts().to_dict()
                    ordered_groups = [k for k, v in sorted(group_counts.items(), key=lambda x: -x[1]) if v > 0]
                    safe_col = split_col_choice.lower().replace(" ", "_")

                    st.caption(
                        f"Splitting by **{split_col_choice}** — {len(ordered_groups):,} groups. "
                        "Blank values are grouped under 'Unknown'."
                    )

                    select_all_groups = st.checkbox(
                        "Select all groups",
                        value=False,
                        key=f"split_select_all_{safe_col}",
                    )

                    groups_table = pd.DataFrame(
                        [{"Select": select_all_groups, "Group": k, "Rows": group_counts[k]} for k in ordered_groups]
                    )
                    # Key includes the column and select-all state so the editor resets when either changes.
                    edited_groups = st.data_editor(
                        groups_table,
                        column_config={
                            "Select": st.column_config.CheckboxColumn("Select", default=False),
                            "Group": st.column_config.TextColumn("Group"),
                            "Rows": st.column_config.NumberColumn("Rows", format="%d"),
                        },
                        disabled=["Group", "Rows"],
                        hide_index=True,
                        width="stretch",
                        key=f"split_group_editor_{safe_col}_{int(select_all_groups)}",
                    )

                    selected_groups = edited_groups.loc[edited_groups["Select"].fillna(False).astype(bool), "Group"].tolist()

                    if not selected_groups:
                        st.info("Tick one or more groups above to build a combined download.")
                    else:
                        combined_mask = group_series.isin(selected_groups)
                        combined_rows = int(combined_mask.sum())
                        group_order = {g: i for i, g in enumerate(ordered_groups)}

                        def _build_combined(mask=combined_mask, order=group_order, src=final_df, gs=group_series):
                            # Keep rows of the same group together, in the order the groups are listed.
                            # Runs only when the download button is clicked.
                            df = src[mask].assign(__grp_order=gs[mask].map(order))
                            df = df.sort_values("__grp_order", kind="stable").drop(columns="__grp_order")
                            return df.to_csv(index=False).encode("utf-8")

                        sel_col1, sel_col2 = st.columns([2, 1])
                        with sel_col1:
                            st.write(
                                f"**{len(selected_groups):,} group(s) selected** → **{combined_rows:,} rows** "
                                f"({', '.join(selected_groups[:5])}{'…' if len(selected_groups) > 5 else ''})"
                            )
                        with sel_col2:
                            st.download_button(
                                f"⬇️ Download selected ({combined_rows:,} rows)",
                                data=_build_combined,
                                file_name=f"split_{safe_col}_selected_groups.csv",
                                mime="text/csv",
                                type="primary",
                                key=f"dl_combined_split_{safe_col}",
                            )

        with tab_audit:
            st.caption("Rows removed or altered during cleaning, for your own verification — nothing here is in the final file.")

            removed_indian_df = st.session_state.get("removed_indian_df", pd.DataFrame())
            st.write(f"**Removed as Indian contacts:** {len(removed_indian_df):,} rows")
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
                st.caption("Check the 'Matched On' and 'Matched Value' columns to see exactly what triggered each removal.")

            st.divider()

            special_chars_df = st.session_state.get("special_chars_removed_df", pd.DataFrame())
            st.write(f"**Rows separated because special characters were found (uncleaned raw values):** {len(special_chars_df):,} rows")
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
                st.caption("This file is not cleaned. It contains original rows exactly as detected with special characters.")

                # Build cleaned version: strip special chars from all non-email columns
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

        section_header("07-Save the Cleaned Data to a Master List", "Save to Master")
        st.markdown(
            '<div class="upload-card">'
            '💾 Save freshly cleaned contacts back into a Master list — they will be '
            'automatically suppressed on every future run. '
            '<strong>Duplicate emails (already in any master list) are skipped automatically.</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
        if not db_is_ready():
            st.warning(
                "Database not connected — reconnect it (see the banner at the top of the page) "
                "to save these contacts to a Master list."
            )
        else:
            final_df = st.session_state["cleaned_df"]
            try:
                existing_master = db.get_master_lists()
                existing_names = existing_master["name"].tolist() if not existing_master.empty else []
            except Exception as e:
                existing_master = pd.DataFrame()
                existing_names = []
                st.warning(f"Could not load existing Master lists: {e}")

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
                    "✅ New contacts to save",
                    f"{new_count:,}",
                    help="These emails are not yet in any master list and will be added.",
                )
                dedup_col2.metric(
                    "⏭️ Already in master lists",
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
                st.warning(f"Could not run global dedup check: {e}")
                new_count = len(final_df)
                new_mask = pd.Series([True] * len(final_df), index=final_df.index)

            if st.button(
                f"💾 Save {new_count:,} new contacts to Master",
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
                            written = db.upsert_master_contacts(list_id, records)
                        # Master data changed: refresh the dedup preview on the next rerun,
                        # and stop trusting the "already suppressed against all lists" shortcut.
                        st.session_state.pop("_dedup_preview", None)
                        st.session_state.pop("master_suppressed_list_ids", None)
                        st.success(
                            f"✅ Saved {written:,} new contacts into Master list "
                            f"'{clean_target}'. They'll be suppressed on future runs."
                        )
                        st.balloons()
                    except Exception as e:
                        st.error(f"Could not save to the Master list: {e}")
else:
    st.markdown(
        '<div class="lf-inline-panel">'
        '📂 <strong>Upload a raw lead file above</strong> and click '
        '<strong>"Use Selected File"</strong> to begin. '
        'Master and Bounce suppression are pulled from your database — '
        'pick which lists to apply in Step 03.'
        '</div>',
        unsafe_allow_html=True,
    )