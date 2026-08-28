"""
LeadFlow — shared data I/O and column mapping
---------------------------------------------

File reading (CSV / XLSX / XLS / ZIP / GZ), upload-size guards, header
auto-detection and column mapping. Shared by the main cleaning page and the
Manage Suppression Database page so both parse uploads identically.
"""

import gzip
import re
import zipfile

import pandas as pd
import streamlit as st


# Final canonical column order used across the app.
FINAL_COLUMNS = ["First Name", "Last Name", "Company", "Email", "Job Title", "Industry", "Location"]

# Header synonyms used for auto-detecting columns in messy raw files.
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


def extract_emails_from_file(df):
    """Best-effort: return a Series of emails from an arbitrary uploaded file.

    Uses column auto-detection; used when importing bounce files where only the
    email address matters.
    """
    mapping = auto_map_columns(df)
    email_col = mapping.get("Email")
    if email_col and email_col in df.columns:
        return df[email_col].dropna().astype(str)
    return pd.Series([], dtype=str)
