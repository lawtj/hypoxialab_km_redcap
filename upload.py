import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import numpy as np
import math
from redcap import Project

def st_load_project(key):
    api_key = st.secrets[key]
    api_url = 'https://redcap.ucsf.edu/api/'
    project = Project(api_url, api_key)
    df = project.export_records(format_type='df')
    return df

# start layout

st.header('Import KM file to RedCap')
st.write('Instructions: Drop the raw KM export file into the box below. Fill in the study ID.')

location = st.selectbox('Select Location', ['UCSF','Uganda'], placeholder='Select Location', index=0)

upi = st.number_input('Unique Patient ID', min_value=1, step=1)

if upi > 0 and upi < 500 and location == 'UCSF': # little reminder to ensure that the session number and patient id is not flipped
    st.markdown('🚨 Be careful! The entered patient id is <500. Remember to double check :)')

if location == 'UCSF':
    session = st.number_input('Session #', min_value=1, step=1) # make sure session can only be an integer
    konica = st_load_project('token')
    # 1) check if the entered session number already exists in REDCap KONICA database
    if session in konica['session'].unique(): # check to prevent duplicate uploads
        st.markdown('🚨 The KM data for this session has already been uploaded. See below to compare if it is the same set of data stored in redcap database.')
        session_data = konica[konica['session'] == session]
        st.write(session_data)
        print(konica.columns)
        st.stop() # stop execution here so nothing below runs
        
    # 2) check if the session number and patient ID pair entered matches with what is in REDCap SESSION, if the session number exists in REDCap SESSION database. 
    session_proj = st_load_project('REDCAP_SESSION').reset_index()
    session_proj['_record_str']  = session_proj['record_id'].astype('string').str.strip()
    session_proj['_patient_str'] = session_proj['patient_id'].astype('string').str.strip()
    session_str = str(session).strip()
    upi_str     = str(upi).strip()
    
    sess_rows = session_proj.loc[session_proj["_record_str"] == session_str]
    if not sess_rows.empty: # session exists in REDCap
        upi_session_pair_found = (sess_rows["_patient_str"] == upi_str).any()
        if not upi_session_pair_found:
            st.error("🚨 The (Patient ID, Session #) pair you entered does not match with what is in REDCap SESSION. Please double check.")
            st.session_state["errors"] = True
            st.session_state.pop("finaldf", None)
            st.stop()
    
    operator = st.selectbox(':scientist: Select KM operator', ['Caroline','Ella','Lily','Rene'], placeholder='Select Operator', index=None)
    api_key = st.secrets['token']
    api_url = 'https://redcap.ucsf.edu/api/'
else:
    session = None  # Or any default value or handling for Uganda
    operator = st.selectbox(':scientist: Select KM operator', ['Ronald'], placeholder='Select Operator', index=None)
    api_key = st.secrets['token_uganda']
    api_url = 'https://redcap.ace.ac.ug/api/'

if upi >= 1:
    if location == 'UCSF' and session is not None and session >= 1 or location == 'Uganda':
        uploaded_file = st.file_uploader('Konica Minolta CSV file', type='csv')
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            #df = df.drop(['Unnamed: 45'], axis=1)
            df['upi'] = int(upi)
            if location == 'UCSF':
                df['session'] = int(session)
            else:
                df['session'] = None  # Or handle as needed for Uganda
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
            st.write('file accepted')
            st.write(df.head())
            
            # the following code is added for ita check - the ita is not going to be included in the redcap upload
            def ita(row, lab_l, lab_b):
                return (np.arctan((row[lab_l]-50)/row[lab_b])) * (180/math.pi)
            
            df_ita = df.copy()
            df_ita['ita'] = df_ita.apply(ita, args=('lab_l', 'lab_b'), axis=1) # added for ita check
            
            
            
            one, two = st.columns(2)
            with one:
                st.write("Checking ITA by Group...")
                st.write(df_ita[['group','ita']]) 
                
            with two:
                st.write('ITA range by Group')
                st.write(df_ita.groupby('group').apply(lambda x: x['ita'].max() - x['ita'].min()).reset_index(name='ita_range'))
                
            # ---------------------------------------------
            ita_by_group_scatter_plot = px.scatter(df_ita, x='group', y='ita', title='ITA by Group')
            st.plotly_chart(ita_by_group_scatter_plot)
            csv = df.to_csv(index=False).encode('utf-8')
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
                    r = requests.post(api_url,data=data)
                st.write('HTTP Status: ' + str(r.status_code))
                st.write(r.text)