import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import numpy as np
from redcap import Project

KONICA_CHECK_FIELDS = ('session', 'group', 'date', 'lab_l', 'lab_a', 'lab_b')
SESSION_CHECK_FIELDS = ('record_id', 'patient_id')

@st.cache_data(ttl=300, show_spinner=False)
def _st_load_project_cached(key, fields=None):
    api_key = st.secrets[key]
    api_urls = [
        'https://redcap.ucsf.edu/api/',
        'https://redcap.ace.ac.ug/api/',
    ]
    last_error = None
    export_kwargs = {'format_type': 'df'}
    if fields:
        export_kwargs['fields'] = list(fields)

    for api_url in api_urls:
        try:
            project = Project(api_url, api_key)
            return project.export_records(**export_kwargs)
        except Exception as err:
            last_error = err

    st.error(
        "Unable to connect to REDCap using either UCSF or ACE Uganda API URLs. "
        f"Last error: {last_error}"
    )
    st.stop()

def st_load_project(key, fields=None):
    fields_tuple = tuple(fields) if fields else None
    return _st_load_project_cached(key, fields_tuple)

def normalize_id(value):
    value_str = str(value).strip()
    try:
        return str(int(float(value_str)))
    except (TypeError, ValueError):
        return value_str

# start layout

st.header('Import KM file to RedCap')
st.write('Instructions: Drop the raw KM export file into the box below. Fill in the study ID.')

location = st.selectbox('Select Location', ['UCSF','Uganda'], placeholder='Select Location', index=0)

if location == 'UCSF':
    data_type = 'study session'
    session_key = 'REDCAP_SESSION'
    konica_key = 'token'
    operator_options = ['Lea','Rene']
    api_key = st.secrets['token']
    api_url = 'https://redcap.ucsf.edu/api/'
else:
    data_type = st.selectbox('Upload Data Type', ['screening data', 'study session'], index=0)
    # session_key = 'Uganda_REDCAP_SESSION'
    # konica_key = 'Uganda_REDCAP_KONICA'
    session_key = 'Uganda_REDCAP_SESSION_UCSF'
    konica_key = 'Uganda_REDCAP_KONICA_UCSF'
    operator_options = ['Ronald', 'Philip', 'Emma']
    # api_key = st.secrets['Uganda_REDCAP_KONICA']
    api_key = st.secrets['Uganda_REDCAP_KONICA_UCSF']
    # api_url = 'https://redcap.ace.ac.ug/api/'
    api_url = 'https://redcap.ucsf.edu/api/'

is_study_session = (data_type == 'study session')

if is_study_session:
    upi = st.number_input('Unique Patient ID', min_value=1, step=1)
    if upi > 0 and upi < 500 and location == 'UCSF': # little reminder to ensure that the session number and patient id is not flipped
        st.markdown('🚨 Be careful! The entered patient id is <500. Remember to double check :)')
    session = st.number_input('Session #', min_value=1, step=1) # make sure session can only be an integer
    operator = st.selectbox(':scientist: Select KM operator', operator_options, placeholder='Select Operator', index=None)
else:
    upi = None
    session = None
    operator = None

konica = None
requires_session_check = is_study_session

if requires_session_check:
    konica = st_load_project(konica_key, KONICA_CHECK_FIELDS)
    session_str = normalize_id(session)

    # 1) check if the entered session number already exists in REDCap KONICA database
    if 'session' in konica.columns:
        konica_session_str = konica['session'].astype('string').str.strip().map(normalize_id)
        if (konica_session_str == session_str).any(): # check to prevent duplicate uploads
            st.markdown('🚨 The KM data for this session has already been uploaded.')
            st.stop() # stop execution here so nothing below runs
    else:
        st.warning("Session column not found in KONICA project. Skipping existing-session check.")

    # 2) check if the session number and patient ID pair entered matches with what is in REDCap SESSION, if the session number exists in REDCap SESSION database.
    session_proj = st_load_project(session_key, SESSION_CHECK_FIELDS).reset_index()
    required_cols = {'record_id', 'patient_id'}
    if not required_cols.issubset(session_proj.columns):
        st.error("🚨 REDCap SESSION project is missing required fields: record_id and/or patient_id.")
        st.stop()

    session_proj['_record_str'] = session_proj['record_id'].astype('string').str.strip().map(normalize_id)
    session_proj['_patient_str'] = session_proj['patient_id'].astype('string').str.strip().map(normalize_id)
    upi_str = normalize_id(upi)

    sess_rows = session_proj.loc[session_proj["_record_str"] == session_str]
    found_patient_ids = sorted(
        set(sess_rows["_patient_str"].dropna().astype("string").str.strip().tolist())
    )
    upi_session_pair_found = (sess_rows["_patient_str"] == upi_str).any() if not sess_rows.empty else False
    if not upi_session_pair_found:
        if found_patient_ids:
            detail_line = (
                f"- Session #{session_str}, Patient ID entered is {upi_str}, "
                f"Patient ID found in REDCap SESSION is {', '.join(found_patient_ids)}."
            )
        else:
            detail_line = (
                f"- Session #{session_str}, Patient ID entered is {upi_str}, "
                "no Patient ID found in REDCap SESSION."
            )
        st.error(
            "🚨 The (Patient ID, Session #) pair you entered does not match with what is in REDCap SESSION.\n\n"
            f"{detail_line}\n\n"
            "Please double check."
        )
        st.session_state["errors"] = True
        st.session_state.pop("finaldf", None)
        st.stop()

study_session_inputs_ready = bool(
    is_study_session and upi is not None and upi >= 1 and session is not None and session >= 1 and operator is not None
)
if (not requires_session_check) or study_session_inputs_ready:
        uploaded_file = st.file_uploader('Konica Minolta CSV file', type='csv')
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            #df = df.drop(['Unnamed: 45'], axis=1)
            df['upi'] = int(upi) if upi is not None else None
            df['session'] = int(session) if session is not None else None
            df['operator'] = operator
            df.rename_axis('record_id', inplace=True)
            df = df.reset_index()
            df = df[['record_id','upi','session','Group', 'Data Name', 'Comment', 'Date', 'Time', 'Melanin Index',
        'Hb Index', 'Hb SO2 Index(%)', 'Hue', 'Value', 'Chroma', 'L*', 'a*',
        'b*', '400', '410', '420', '430', '440', '450', '460', '470', '480',
        '490', '500', '510', '520', '530', '540', '550', '560', '570', '580',
        '590', '600', '610', '620', '630', '640', '650', '660', '670', '680',
        '690', '700','operator']]
            df.columns = ['record_id', 'upi', 'session','group', 'data_name', 'comment', 'date', 'time',
        'melanin_index', 'hb_index', 'hb_so2_index', 'hue', 'value', 'chroma',
        'lab_l', 'lab_a', 'lab_b', 'km400', 'km410', 'km420', 'km430', 'km440',
        'km450', 'km460', 'km470', 'km480', 'km490', 'km500', 'km510', 'km520',
        'km530', 'km540', 'km550', 'km560', 'km570', 'km580', 'km590', 'km600',
        'km610', 'km620', 'km630', 'km640', 'km650', 'km660', 'km670', 'km680',
        'km690', 'km700','operator']
            
            st.write(df.head())
            
            df_ita = df.copy()
            df_ita['lab_l'] = pd.to_numeric(df_ita['lab_l'], errors='coerce')
            df_ita['lab_b'] = pd.to_numeric(df_ita['lab_b'], errors='coerce')
            # Vectorized ITA computation to avoid slow row-wise apply.
            df_ita['ita'] = np.degrees(np.arctan((df_ita['lab_l'] - 50) / df_ita['lab_b']))
            
            one, two = st.columns(2)
            with one:
                st.write("Checking ITA by Group...")
                st.write(df_ita[['group','ita']]) 
                
            with two:
                st.write('ITA range by Group')
                ita_range = (
                    df_ita.groupby('group', dropna=False)['ita']
                    .agg(lambda values: values.max() - values.min())
                    .reset_index(name='ita_range')
                )
                st.write(ita_range)
                
            ita_by_group_scatter_plot = px.scatter(df_ita, x='group', y='ita', title='ITA by Group')
            st.plotly_chart(ita_by_group_scatter_plot)
            
            # Columns to check for duplicates
            if konica is None:
                konica = st_load_project(konica_key, KONICA_CHECK_FIELDS)
            cols_to_check = ['group', 'date', 'lab_l', 'lab_a', 'lab_b']

            # Ensure both dfs have these columns
            cols_to_check = [c for c in cols_to_check if c in df.columns and c in konica.columns]

            # Empty (test) projects can have no comparable columns yet.
            if not cols_to_check:
                st.info("No existing comparable records yet. Skipping duplicate-file check.")
            else:
                # Normalize: coerce numerics, parse date
                df_check = df[cols_to_check].copy()
                konica_check = konica[cols_to_check].copy()

                # Dates to YYYY-MM-DD
                if 'date' in cols_to_check:
                    df_check['date'] = pd.to_datetime(df_check['date'], errors='coerce').dt.strftime('%Y-%m-%d')
                    konica_check['date'] = pd.to_datetime(konica_check['date'], errors='coerce').dt.strftime('%Y-%m-%d')

                # Numerics: lab_l, lab_a, lab_b
                for col in ['lab_l','lab_a','lab_b']:
                    if col in cols_to_check:
                        df_check[col] = pd.to_numeric(df_check[col], errors='coerce').round(6)
                        konica_check[col] = pd.to_numeric(konica_check[col], errors='coerce').round(6)

                # Deduplicate to avoid cartesian blowups
                df_check = df_check.drop_duplicates()
                konica_check = konica_check.drop_duplicates()

                # Compare using set-style key matching to avoid expensive frame merge.
                df_keys = pd.MultiIndex.from_frame(df_check[cols_to_check])
                konica_keys = pd.MultiIndex.from_frame(konica_check[cols_to_check])
                matching_keys = df_keys[df_keys.isin(konica_keys)]
                if len(matching_keys) > 0:
                    detail_lines = []
                    konica_detail = st_load_project(konica_key)
                    detail_cols = [c for c in cols_to_check if c in konica_detail.columns]
                    if detail_cols:
                        konica_detail_check = konica_detail[detail_cols].copy()
                        if 'date' in detail_cols:
                            konica_detail_check['date'] = pd.to_datetime(
                                konica_detail_check['date'], errors='coerce'
                            ).dt.strftime('%Y-%m-%d')
                        for col in ['lab_l', 'lab_a', 'lab_b']:
                            if col in detail_cols:
                                konica_detail_check[col] = pd.to_numeric(
                                    konica_detail_check[col], errors='coerce'
                                ).round(6)

                        konica_detail_keys = pd.MultiIndex.from_frame(konica_detail_check[detail_cols])
                        matched_konica_rows = konica_detail.loc[konica_detail_keys.isin(matching_keys)].copy()

                        if not matched_konica_rows.empty and 'session' in matched_konica_rows.columns:
                            matched_konica_rows['_session_str'] = (
                                matched_konica_rows['session'].astype('string').str.strip().map(normalize_id)
                            )
                            pid_col = None
                            for candidate in ['patient_id', 'upi']:
                                if candidate in matched_konica_rows.columns:
                                    pid_col = candidate
                                    break

                            if pid_col is not None:
                                matched_konica_rows['_pid_str'] = (
                                    matched_konica_rows[pid_col].astype('string').str.strip().map(normalize_id)
                                )
                                for sess_id, grp in matched_konica_rows.groupby('_session_str', dropna=True):
                                    pid_vals = sorted(
                                        set(grp['_pid_str'].dropna().astype('string').str.strip().tolist())
                                    )
                                    if pid_vals:
                                        detail_lines.append(
                                            f"- This file corresponds to Session #{sess_id}, Patient ID {', '.join(pid_vals)} in REDCap database."
                                        )
                                    else:
                                        detail_lines.append(
                                            f"- This file corresponds to Session #{sess_id}, no Patient ID found in REDCap database."
                                        )
                            else:
                                for sess_id in sorted(
                                    set(matched_konica_rows['_session_str'].dropna().astype('string').str.strip().tolist())
                                ):
                                    detail_lines.append(
                                        f"- This file corresponds to Session #{sess_id}, no Patient ID found in REDCap database."
                                    )

                    if not detail_lines:
                        detail_lines.append(
                            f"- This file corresponds to Session #{session_str}, no Patient ID found in REDCap database."
                        )
                    detail_text = "\n".join(detail_lines)
                    st.error(
                        "🚨 Please double check. The file dropped already exists in REDCap database.\n\n"
                        f"{detail_text}"
                    )
                    st.stop()

            st.write('file accepted')
            
            # ---------------------------------------------
            csv = df.to_csv(index=False)
            upload_allowed = is_study_session
            if upload_allowed:
                if st.button('Upload to RedCap'):
                    data = {
                    'token': api_key,
                    'content': 'record',
                    'action': 'import',
                    'format': 'csv',
                    'type': 'flat',
                    'overwriteBehavior': 'normal',
                    'forceAutoNumber': 'true',
                    'data': csv,
                    'dateFormat': 'MDY',
                    'returnContent': 'count',
                    'returnFormat': 'json'
                    }
                    with st.spinner('Uploading to RedCap...'):
                        try:
                            r = requests.post(api_url, data=data, timeout=(10, 120))
                        except requests.RequestException as err:
                            st.error(f"Upload failed: {err}")
                            st.stop()
                    st.write('HTTP Status: ' + str(r.status_code))
                    st.write(r.text)
                    if r.ok:
                        _st_load_project_cached.clear()
            else:
                st.info("Screening data selected: visualization only. Upload to RedCap is disabled.")
elif is_study_session:
    st.info("Please enter Unique Patient ID, Session #, and select KM operator to continue.")
