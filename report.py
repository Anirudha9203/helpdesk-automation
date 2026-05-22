import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import base64
from datetime import date

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="DEXIT Global Helpdesk Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

.main-header {
    background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%);
    border-radius: 12px;
    padding: 28px 36px;
    margin-bottom: 24px;
}

.main-header h1 {
    font-size: 26px;
    font-weight: 700;
    color: #ffffff;
    margin: 0 0 4px 0;
    letter-spacing: -0.3px;
}

.main-header p {
    font-size: 13px;
    color: #e3f0ff;
    margin: 0;
    font-weight: 400;
}

.section-title {
    font-size: 12px;
    font-weight: 700;
    color: #1a73e8;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    margin-bottom: 12px;
}

.metric-card {
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 16px 20px;
    text-align: center;
    background: #f8f9ff;
}

.metric-value {
    font-size: 32px;
    font-weight: 700;
    font-family: 'DM Mono', monospace;
    line-height: 1;
    margin-bottom: 4px;
    color: #1a1d2e;
}

.metric-label {
    font-size: 11px;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 600;
}

.metric-sub {
    font-size: 12px;
    color: #1a73e8;
    font-weight: 500;
    margin-top: 4px;
    font-family: 'DM Mono', monospace;
}

.divider {
    border: none;
    border-top: 1px solid #e0e0e0;
    margin: 20px 0;
}

.alert-warn {
    background: #fff8e1;
    border: 1px solid #f9a825;
    border-radius: 8px;
    padding: 12px 16px;
    color: #e65100;
    font-size: 12px;
    margin-bottom: 16px;
}

.info-box {
    background: #e8f0fe;
    border: 1px solid #1a73e8;
    border-radius: 8px;
    padding: 12px 16px;
    color: #1a73e8;
    font-size: 12px;
    margin-bottom: 16px;
}

h3.sub-section {
    font-size: 14px;
    font-weight: 600;
    color: #1a1d2e;
    margin: 20px 0 12px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid #e0e0e0;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# PIPELINE FUNCTIONS - CALLS
# ─────────────────────────────────────────────

def normalize_category_calls(cat):
    if pd.isna(cat):
        return None
    cat = str(cat).strip()
    mapping = {
        'Exam Related Query': 'Exam related query',
        'Registration Related': 'Registration related',
        'Admit Card Related ': 'Admit Card Related',
        'No voice/ blank call / call disconnect\xa0': 'No voice/ blank call / call disconnect',
        'No voice/ blank call / call disconnect ': 'No voice/ blank call / call disconnect',
        'LMS Related ': 'LMS Related',
        ' Login Issue': 'Login Issue',
        'Candidate Related': 'Candidate related',
    }
    return mapping.get(cat, cat)


def normalize_queue_name1(row):
    q = str(row['Queue Name'])
    proj = row['Project Name']
    if proj == 'Core' and q in ('Mudra_Cell1', 'Mudra_ISA_AT', 'MudraCell2'):
        return 'Mudra'
    if proj == 'Gateway' and q == 'Mudra_HR_SR':
        return 'Mudra'
    disp = str(row.get('User Disposition Code', ''))
    if q == 'UIDAI/IRDA':
        if 'UIDAI' in disp:
            return 'UIDAI'
        if 'NISM' in disp:
            return 'NISM'
        return 'IRDA'
    return q


def run_calls_pipeline(acd_file, call_hist_file, cats_file):
    acd = pd.read_csv(acd_file)
    call_hist = pd.read_csv(call_hist_file)
    calls_cat = pd.read_excel(cats_file)

    # Stage 1: Filter noise
    acd['_wait_td'] = pd.to_timedelta(acd['Total Wait Time'].astype(str), errors='coerce')
    excl = [
        'FraudQ', 'ROSE', 'Helpdesk_Support_2', 'Admin_Support',
        'Exam_Schedule2', 'CPU Queries', 'Admin Support', 'IIBF_ITHELP', 'Rishikesh EC'
    ]
    step1 = acd[~(
        (acd['_wait_td'] <= pd.Timedelta(seconds=10)) &
        (acd['Answered/Hungup'] == 'HUNGUP')
    )].copy()
    step1 = step1[~step1['Queue Name'].isin(excl)].copy()

    short_hangup_removed = len(acd) - len(step1[step1['Queue Name'].isin(excl) == False])
    queue_removed = acd[acd['Queue Name'].isin(excl)].shape[0]

    # Stage 2: Project + Queue Name1
    step1['Project Name'] = step1['Queue Name'].apply(
        lambda x: 'Manage Engine' if x in ('Gateway_Helpdesk', 'Gateway_Helpdesk1', 'IT_Support')
        else 'Core' if x in ('Manchester', 'IBBI', 'IRDA', 'UIDAI', 'UIDAI/IRDA', 'FPSB', 'Mudra', 'MudraCell2', 'Mudra_Cell1', 'Mudra_ISA_AT')
        else 'Gateway'
    )
    step1['Queue Name1'] = step1.apply(normalize_queue_name1, axis=1)

    # Stage 3: Callback reclassification
    step1['Number'] = step1['Phone'].astype(str).str[-10:]
    call_hist['Number'] = call_hist['Phone'].astype(str).str[-10:]
    hung = step1[step1['Answered/Hungup'] == 'HUNGUP'].drop_duplicates(subset='Number')
    connected = call_hist[call_hist['System Disposition'] == 'CONNECTED']
    overlap = set(hung['Number']) & set(connected['Number'])
    step1['HungID'] = step1['Number'] + '_' + step1['Answered/Hungup']
    if 'Call Notes' not in step1.columns:
        step1['Call Notes'] = ''
    step1['Call Notes'] = step1['Call Notes'].astype(str)

    callbacks_done = 0
    for num in overlap:
        agent_rows = connected[connected['Number'] == num]
        if len(agent_rows):
            agent = agent_rows['User Name'].iloc[0]
            mask = step1['HungID'].str.contains(num + '_HUNGUP', regex=False)
            step1.loc[mask, 'Answered/Hungup'] = 'ANSWERED'
            step1.loc[mask, 'Username'] = agent
            step1.loc[mask, 'Call Notes'] = 'Call Back Done'
            callbacks_done += mask.sum()

    call_working = step1.drop(columns=['Number', 'HungID', '_wait_td'], errors='ignore')

    # Stage 4: Bifurcation
    cats_clean = calls_cat.drop_duplicates(subset=[' Sub Category'])
    bif_input = call_working[
        (call_working['Answered/Hungup'] == 'ANSWERED') &
        (call_working['Project Name'].isin(['Core', 'Gateway']))
    ].copy()
    bif = pd.merge(
        bif_input,
        cats_clean[[' Sub Category', ' Category']],
        left_on='User Disposition Code',
        right_on=' Sub Category',
        how='left'
    )
    bif.loc[bif['Call Notes'] == 'Call Back Done', ' Category'] = 'Call Back Done'
    bif[' Category'] = bif[' Category'].apply(normalize_category_calls)
    bif = bif.rename(columns={' Category': 'Types of Queries'})

    stats = {
        'raw_total': len(acd),
        'after_filter': len(call_working),
        'callbacks': callbacks_done,
        'answered': len(call_working[call_working['Answered/Hungup'] == 'ANSWERED']),
        'hungup': len(call_working[call_working['Answered/Hungup'] == 'HUNGUP']),
        'core': len(call_working[call_working['Project Name'] == 'Core']),
        'gateway': len(call_working[call_working['Project Name'] == 'Gateway']),
        'bifurcation_total': len(bif),
        'bifurcation_matched': bif['Types of Queries'].notna().sum(),
        'bifurcation_unmatched': bif['Types of Queries'].isna().sum(),
    }
    return call_working, bif, stats


# ─────────────────────────────────────────────
# PIPELINE FUNCTIONS - MAILS
# ─────────────────────────────────────────────

CORE_QUEUES = [
    "UIDAI_Admin", "III EXCEPTION", "iii_Exam_1", "Manchester",
    "III_Exams_Schedule", "Mudra", "IBBI Exam",
    "UIDAI_Admin_DEX", "Exam_Schedule_DEX", "ChargeBack_DEX"
]


def run_mails_pipeline(mail_file, mail_cat_file, selected_date=None):
    mail = pd.read_excel(mail_file)
    mail_cat = pd.read_excel(mail_cat_file)

    mail_df = mail[mail['Channel'] == 'INCOMING_MAIL'].copy()
    mail_df['Closed On dt'] = pd.to_datetime(mail_df['Closed On'], errors='coerce')
    mail_df['Closed Date'] = mail_df['Closed On dt'].dt.date
    mail_df['Closed Time'] = mail_df['Closed On dt'].dt.time

    available_dates = sorted(mail_df['Closed Date'].dropna().unique())

    if selected_date is not None:
        mail_df = mail_df[mail_df['Closed Date'] == selected_date].copy()

    mail_df['Queue Type'] = mail_df['Queue Name'].apply(
        lambda x: "Core" if x in CORE_QUEUES else "Gateway"
    )

    mail_df['_ct_null'] = mail_df['Client Type: Type'].isna()
    mail_df['Client Type: Type'] = mail_df['Client Type: Type'].astype(str).str.strip()

    mail_cat_clean = (
        mail_cat[['Sub Category', 'Category']]
        .dropna(subset=['Sub Category'])
        .drop_duplicates(subset=['Sub Category'])
        .copy()
    )
    mail_cat_clean['Sub Category'] = mail_cat_clean['Sub Category'].astype(str).str.strip()

    mail_df = mail_df.merge(
        mail_cat_clean,
        how='left',
        left_on='Client Type: Type',
        right_on='Sub Category'
    )
    mail_df.loc[mail_df['_ct_null'] == True, 'Category'] = 'Bulk Closure/No Tagging/Blank Mail'
    mail_df['Category'] = mail_df['Category'].fillna('Unknown')
    mail_df['Bifurcation'] = mail_df['Category']
    mail_df = mail_df.drop(columns=['_ct_null', 'Sub Category'], errors='ignore')

    stats = {
        'total_incoming': len(mail_df),
        'core': len(mail_df[mail_df['Queue Type'] == 'Core']),
        'gateway': len(mail_df[mail_df['Queue Type'] == 'Gateway']),
        'bulk_closure': (mail_df['Bifurcation'] == 'Bulk Closure/No Tagging/Blank Mail').sum(),
        'categorized': (mail_df['Bifurcation'] != 'Unknown').sum(),
        'unknown': (mail_df['Bifurcation'] == 'Unknown').sum(),
        'sla_assign_achieved': (mail_df['Assign Time SLA'] == 'ACHIEVED').sum(),
        'sla_first_resp_breached': (mail_df['First Resonse SLA'] == 'BREACHED').sum(),
        'sla_resolve_achieved': (mail_df['Resolve Time SLA'] == 'ACHIEVED').sum(),
    }
    return mail_df, stats, available_dates


# ─────────────────────────────────────────────
# RENDER FUNCTIONS
# ─────────────────────────────────────────────

def render_pivot_html(df, label_col, value_cols, total_row=True, abandon_col=None):
    rows_html = ""
    for _, row in df.iterrows():
        is_total = str(row[label_col]).lower() in ['all', 'grand total', 'total']
        row_class = "total-row" if is_total else ""
        cells = f'<td class="label-col">{row[label_col]}</td>'
        for col in value_cols:
            val = row.get(col, 0)
            if col == abandon_col and not is_total:
                if isinstance(val, float):
                    pct = val
                    cls = "abandon-high" if pct > 10 else ("abandon-med" if pct > 5 else "abandon-low")
                    cells += f'<td class="num-col {cls}">{pct:.1f}%</td>'
                else:
                    cells += f'<td class="num-col">{val}</td>'
            else:
                if isinstance(val, float) and not col == abandon_col:
                    cells += f'<td class="num-col">{int(val) if val == int(val) else val}</td>'
                else:
                    cells += f'<td class="num-col">{val}</td>'
        rows_html += f'<tr class="{row_class}">{cells}</tr>'

    headers = "".join(f'<th>{c}</th>' for c in [label_col] + value_cols)
    return f'<table class="pivot-table"><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>'


def pivot_to_df_display(pivot_df, index_name="Row Labels"):
    df = pivot_df.reset_index()
    df.columns.name = None
    df = df.rename(columns={df.columns[0]: index_name})
    return df


def build_excel_calls(call_working, bif):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        wb = writer.book

        # Formats
        hdr_fmt = wb.add_format({'bold': True, 'bg_color': '#1c2033', 'font_color': '#8891aa', 'border': 1, 'font_size': 10})
        cell_fmt = wb.add_format({'font_size': 10, 'border': 1, 'font_color': '#333333'})
        total_fmt = wb.add_format({'bold': True, 'font_size': 10, 'border': 1, 'bg_color': '#e8e8e8'})
        pct_fmt = wb.add_format({'num_format': '0.0"%"', 'font_size': 10, 'border': 1})
        title_fmt = wb.add_format({'bold': True, 'font_size': 12, 'font_color': '#1a1d2e'})

        def write_pivot(ws, df, row_start, col_start, title):
            ws.write(row_start, col_start, title, title_fmt)
            row_start += 1
            cols = list(df.columns)
            for ci, c in enumerate(cols):
                ws.write(row_start, col_start + ci, str(c), hdr_fmt)
            for ri, (_, row) in enumerate(df.iterrows()):
                is_total = str(row.iloc[0]).lower() in ['all', 'grand total']
                fmt = total_fmt if is_total else cell_fmt
                for ci, v in enumerate(row):
                    ws.write(row_start + 1 + ri, col_start + ci, v, fmt)

        # Sheet 1: Summary
        ws1 = wb.add_worksheet('Summary')
        proj_count = call_working['Project Name'].value_counts().reset_index()
        proj_count.columns = ['Project Name', 'Total']
        proj_count['%'] = (proj_count['Total'] / proj_count['Total'].sum() * 100).round(1).astype(str) + '%'
        total_row = pd.DataFrame([['Grand Total', proj_count['Total'].sum(), '100%']], columns=proj_count.columns)
        proj_count = pd.concat([proj_count, total_row], ignore_index=True)
        write_pivot(ws1, proj_count, 0, 0, 'Overall Call Count by Project')
        ws1.set_column(0, 3, 18)

        # Sheet 2: Core Calls
        ws2 = wb.add_worksheet('Core Queue Calls')
        core_piv = pd.pivot_table(
            call_working[call_working['Project Name'] == 'Core'],
            values='#', index='Queue Name1', columns='Answered/Hungup',
            aggfunc='count', fill_value=0, margins=True, margins_name='Grand Total'
        ).reset_index()
        core_piv.columns.name = None
        if 'HUNGUP' not in core_piv.columns:
            core_piv['HUNGUP'] = 0
        core_piv['Grand Total'] = core_piv.get('ANSWERED', 0) + core_piv.get('HUNGUP', 0)
        core_piv['Abandon %'] = (core_piv.get('HUNGUP', 0) / core_piv['Grand Total'].replace(0, np.nan) * 100).round(1)
        write_pivot(ws2, core_piv, 0, 0, 'Core Projectwise Call Count')
        ws2.set_column(0, 5, 20)

        # Sheet 3: Gateway Calls
        ws3 = wb.add_worksheet('Gateway Queue Calls')
        gw_piv = pd.pivot_table(
            call_working[call_working['Project Name'] == 'Gateway'],
            values='#', index='Queue Name1', columns='Answered/Hungup',
            aggfunc='count', fill_value=0, margins=True, margins_name='Grand Total'
        ).reset_index()
        gw_piv.columns.name = None
        if 'HUNGUP' not in gw_piv.columns:
            gw_piv['HUNGUP'] = 0
        gw_piv['Grand Total2'] = gw_piv.get('ANSWERED', 0) + gw_piv.get('HUNGUP', 0)
        gw_piv['Abandon %'] = (gw_piv.get('HUNGUP', 0) / gw_piv['Grand Total2'].replace(0, np.nan) * 100).round(1)
        write_pivot(ws3, gw_piv, 0, 0, 'Gateway Projectwise Call Count')
        ws3.set_column(0, 5, 22)

        # Sheet 4: Agent Calls
        ws4 = wb.add_worksheet('Agentwise Calls')
        agent_piv = pd.pivot_table(
            call_working, values='#', index='Username',
            columns='Project Name', aggfunc='count', fill_value=0,
            margins=True, margins_name='Grand Total'
        ).reset_index()
        agent_piv.columns.name = None
        write_pivot(ws4, agent_piv, 0, 0, 'Agentwise Call Count')
        ws4.set_column(0, 5, 22)

        # Sheet 5: Call Bifurcation
        ws5 = wb.add_worksheet('Call Bifurcation')
        bif_piv = pd.pivot_table(
            bif, values='#', index='Types of Queries',
            columns='Project Name', aggfunc='count', fill_value=0,
            margins=True, margins_name='Grand Total'
        ).reset_index()
        bif_piv.columns.name = None
        bif_blank = bif[bif['Types of Queries'].isna()].assign(**{'Types of Queries': '(Unmatched)'})
        if len(bif_blank):
            blank_piv = pd.pivot_table(
                bif_blank, values='#', index='Types of Queries',
                columns='Project Name', aggfunc='count', fill_value=0
            ).reset_index()
            blank_piv.columns.name = None
        write_pivot(ws5, bif_piv, 0, 0, 'Call Bifurcation by Query Type')
        ws5.set_column(0, 4, 35)

        # Sheet 6: Raw Working
        call_working.to_excel(writer, sheet_name='Call Working (Raw)', index=False)
        bif.to_excel(writer, sheet_name='Bifurcation (Raw)', index=False)

    return output.getvalue()


def build_excel_mails(mail_df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        wb = writer.book
        hdr_fmt = wb.add_format({'bold': True, 'bg_color': '#d0e4ff', 'border': 1, 'font_size': 10})
        cell_fmt = wb.add_format({'font_size': 10, 'border': 1})
        total_fmt = wb.add_format({'bold': True, 'font_size': 10, 'border': 1, 'bg_color': '#e8e8e8'})
        title_fmt = wb.add_format({'bold': True, 'font_size': 12})

        def write_pivot(ws, df, row_start, col_start, title):
            ws.write(row_start, col_start, title, title_fmt)
            row_start += 1
            for ci, c in enumerate(df.columns):
                ws.write(row_start, col_start + ci, str(c), hdr_fmt)
            for ri, (_, row) in enumerate(df.iterrows()):
                is_total = str(row.iloc[0]).lower() in ['all', 'grand total']
                fmt = total_fmt if is_total else cell_fmt
                for ci, v in enumerate(row):
                    ws.write(row_start + 1 + ri, col_start + ci, v, fmt)

        ws1 = wb.add_worksheet('Queue Summary')
        q_piv = pd.pivot_table(mail_df, values='#', index='Queue Name', columns='Queue Type', aggfunc='count', fill_value=0, margins=True, margins_name='Grand Total').reset_index()
        q_piv.columns.name = None
        write_pivot(ws1, q_piv, 0, 0, 'Mail Count by Queue and Project')
        ws1.set_column(0, 4, 22)

        ws2 = wb.add_worksheet('Agentwise Mails')
        a_piv = pd.pivot_table(mail_df, values='#', index='Agent', columns='Queue Type', aggfunc='count', fill_value=0, margins=True, margins_name='Grand Total').reset_index()
        a_piv.columns.name = None
        write_pivot(ws2, a_piv, 0, 0, 'Mail Count by Agent and Project')
        ws2.set_column(0, 4, 22)

        ws3 = wb.add_worksheet('Mail Bifurcation')
        b_piv = pd.pivot_table(mail_df, values='#', index='Bifurcation', columns='Queue Type', aggfunc='count', fill_value=0, margins=True, margins_name='Grand Total').reset_index()
        b_piv.columns.name = None
        write_pivot(ws3, b_piv, 0, 0, 'Mail Bifurcation by Category and Project')
        ws3.set_column(0, 4, 35)

        ws4 = wb.add_worksheet('SLA Summary')
        sla_data = {
            'SLA Type': ['Assign Time SLA', 'First Response SLA', 'Resolve Time SLA'],
            'Achieved': [
                (mail_df['Assign Time SLA'] == 'ACHIEVED').sum(),
                (mail_df['First Resonse SLA'] == 'ACHIEVED').sum(),
                (mail_df['Resolve Time SLA'] == 'ACHIEVED').sum(),
            ],
            'Breached': [
                (mail_df['Assign Time SLA'] == 'BREACHED').sum(),
                (mail_df['First Resonse SLA'] == 'BREACHED').sum(),
                (mail_df['Resolve Time SLA'] == 'BREACHED').sum(),
            ],
        }
        sla_df = pd.DataFrame(sla_data)
        sla_df['Total'] = sla_df['Achieved'] + sla_df['Breached']
        sla_df['Breach %'] = (sla_df['Breached'] / sla_df['Total'].replace(0, np.nan) * 100).round(1).astype(str) + '%'
        write_pivot(ws4, sla_df, 0, 0, 'SLA Performance Summary')
        ws4.set_column(0, 5, 22)

        mail_df.to_excel(writer, sheet_name='Processed Data (Raw)', index=False)

    return output.getvalue()


def build_html_report_calls(call_working, bif, stats, report_date=None):
    date_str = report_date.strftime('%d %B %Y') if report_date else date.today().strftime('%d %B %Y')

    # Overall
    proj_count = call_working['Project Name'].value_counts()
    total_calls = len(call_working)

    # Core pivot
    core_data = call_working[call_working['Project Name'] == 'Core']
    core_piv = pd.pivot_table(core_data, values='#', index='Queue Name1', columns='Answered/Hungup', aggfunc='count', fill_value=0)
    if 'HUNGUP' not in core_piv.columns:
        core_piv['HUNGUP'] = 0
    if 'ANSWERED' not in core_piv.columns:
        core_piv['ANSWERED'] = 0
    core_piv['Total'] = core_piv['ANSWERED'] + core_piv['HUNGUP']
    core_piv['Abandon %'] = (core_piv['HUNGUP'] / core_piv['Total'].replace(0, np.nan) * 100).round(1)
    core_piv = core_piv.reset_index().rename(columns={'Queue Name1': 'Queue'})
    total_row_core = pd.DataFrame([{
        'Queue': 'Grand Total',
        'ANSWERED': core_piv['ANSWERED'].sum(),
        'HUNGUP': core_piv['HUNGUP'].sum(),
        'Total': core_piv['Total'].sum(),
        'Abandon %': round(core_piv['HUNGUP'].sum() / core_piv['Total'].sum() * 100, 1)
    }])
    core_piv = pd.concat([core_piv, total_row_core], ignore_index=True)

    # Gateway pivot
    gw_data = call_working[call_working['Project Name'] == 'Gateway']
    gw_piv = pd.pivot_table(gw_data, values='#', index='Queue Name1', columns='Answered/Hungup', aggfunc='count', fill_value=0)
    if 'HUNGUP' not in gw_piv.columns:
        gw_piv['HUNGUP'] = 0
    if 'ANSWERED' not in gw_piv.columns:
        gw_piv['ANSWERED'] = 0
    gw_piv['Total'] = gw_piv['ANSWERED'] + gw_piv['HUNGUP']
    gw_piv['Abandon %'] = (gw_piv['HUNGUP'] / gw_piv['Total'].replace(0, np.nan) * 100).round(1)
    gw_piv = gw_piv.reset_index().rename(columns={'Queue Name1': 'Queue'})
    total_row_gw = pd.DataFrame([{
        'Queue': 'Grand Total',
        'ANSWERED': gw_piv['ANSWERED'].sum(),
        'HUNGUP': gw_piv['HUNGUP'].sum(),
        'Total': gw_piv['Total'].sum(),
        'Abandon %': round(gw_piv['HUNGUP'].sum() / gw_piv['Total'].sum() * 100, 1)
    }])
    gw_piv = pd.concat([gw_piv, total_row_gw], ignore_index=True)

    # Agent pivot
    agent_piv = pd.pivot_table(call_working, values='#', index='Username', columns='Project Name', aggfunc='count', fill_value=0).reset_index()
    agent_piv.columns.name = None
    agent_piv['Total'] = agent_piv.drop(columns=['Username']).sum(axis=1)
    agent_piv = agent_piv.sort_values('Total', ascending=False)

    # Query type pivot
    tq_piv = pd.pivot_table(bif, values='#', index='Types of Queries', columns='Project Name', aggfunc='count', fill_value=0).reset_index()
    tq_piv.columns.name = None
    tq_piv['Total'] = tq_piv.drop(columns=['Types of Queries']).sum(axis=1)
    tq_piv = tq_piv.sort_values('Total', ascending=False)

    def df_to_html_table(df, abandon_col=None):
        rows = ""
        for _, row in df.iterrows():
            is_total = str(row.iloc[0]).lower() in ['grand total']
            tr_class = ' class="total"' if is_total else ''
            cells = f'<td class="label">{row.iloc[0]}</td>'
            for i, col in enumerate(df.columns[1:]):
                val = row[col]
                extra_class = ''
                if abandon_col and col == abandon_col and not is_total:
                    if isinstance(val, float):
                        extra_class = ' abandon-high' if val > 10 else (' abandon-med' if val > 5 else ' abandon-low')
                        cells += f'<td class="num{extra_class}">{val:.1f}%</td>'
                        continue
                if isinstance(val, float) and val == int(val):
                    val = int(val)
                cells += f'<td class="num{extra_class}">{val}</td>'
            rows += f'<tr{tr_class}>{cells}</tr>'

        headers = ''.join(f'<th>{c}</th>' for c in df.columns)
        return f'<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Call Report - {date_str}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'DM Sans', sans-serif; background: #fff; color: #1a1d2e; font-size: 11px; }}
  .header {{ background: #1a1d2e; color: #fff; padding: 18px 24px; margin-bottom: 20px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }}
  .header .meta {{ font-size: 11px; color: #8891aa; text-align: right; }}
  .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }}
  .metric {{ background: #f7f8fc; border: 1px solid #e0e3ed; border-radius: 6px; padding: 12px 14px; text-align: center; }}
  .metric .val {{ font-size: 26px; font-weight: 700; color: #1a1d2e; font-family: 'DM Mono', monospace; }}
  .metric .lbl {{ font-size: 9px; color: #6b7494; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; margin-top: 3px; }}
  .metric .sub {{ font-size: 10px; color: #5c7cfa; font-family: 'DM Mono', monospace; margin-top: 2px; font-weight: 500; }}
  .section {{ margin-bottom: 22px; break-inside: avoid; }}
  .section-title {{ font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: #5c7cfa; margin-bottom: 8px; padding-bottom: 5px; border-bottom: 1.5px solid #e0e3ed; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{ background: #f0f2f8; color: #6b7494; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.7px; padding: 7px 10px; text-align: left; border-bottom: 1.5px solid #d0d4e8; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #f0f2f8; color: #2d3150; }}
  td.label {{ font-weight: 500; }}
  td.num {{ text-align: right; font-family: 'DM Mono', monospace; }}
  tr.total td {{ background: #f0f2f8; font-weight: 700; color: #1a1d2e; border-top: 1.5px solid #d0d4e8; }}
  .abandon-high {{ color: #c0392b; font-weight: 700; }}
  .abandon-med {{ color: #e67e22; font-weight: 600; }}
  .abandon-low {{ color: #27ae60; }}
  .footer {{ text-align: center; font-size: 9px; color: #8891aa; margin-top: 20px; padding-top: 10px; border-top: 1px solid #e0e3ed; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>NSEIT Helpdesk - Call Report</h1>
    <div style="font-size:11px;color:#8891aa;margin-top:3px;">Inbound Call Analysis | Processed {stats['after_filter']} calls</div>
  </div>
  <div class="meta">
    <div style="font-size:13px;font-weight:600;color:#fff;">{date_str}</div>
    <div>Auto-generated report</div>
  </div>
</div>

<div class="metrics">
  <div class="metric"><div class="val">{stats['after_filter']}</div><div class="lbl">Total Calls</div><div class="sub">After Filtering</div></div>
  <div class="metric"><div class="val">{stats['answered']}</div><div class="lbl">Answered</div><div class="sub">{round(stats['answered']/stats['after_filter']*100,1)}% answer rate</div></div>
  <div class="metric"><div class="val">{stats['hungup']}</div><div class="lbl">Abandoned</div><div class="sub">{round(stats['hungup']/stats['after_filter']*100,1)}% abandon rate</div></div>
  <div class="metric"><div class="val">{stats['callbacks']}</div><div class="lbl">Callbacks Done</div><div class="sub">Hung-up recovered</div></div>
</div>

<div class="two-col">
  <div class="section">
    <div class="section-title">Core Projectwise Call Count</div>
    {df_to_html_table(core_piv, abandon_col='Abandon %')}
  </div>
  <div class="section">
    <div class="section-title">Gateway Projectwise Call Count</div>
    {df_to_html_table(gw_piv, abandon_col='Abandon %')}
  </div>
</div>

<div class="section">
  <div class="section-title">Agentwise Call Count</div>
  {df_to_html_table(agent_piv)}
</div>

<div class="section">
  <div class="section-title">Call Bifurcation - Types of Queries</div>
  {df_to_html_table(tq_piv)}
</div>

<div class="footer">NSEIT Helpdesk Dashboard | {date_str} | This report is auto-generated. Do not edit manually.</div>
</body></html>"""

    return html


def build_html_report_mails(mail_df, stats, selected_date=None):
    date_str = selected_date.strftime('%d %B %Y') if selected_date else date.today().strftime('%d %B %Y')

    q_piv = pd.pivot_table(mail_df, values='#', index='Queue Name', columns='Queue Type', aggfunc='count', fill_value=0).reset_index()
    q_piv.columns.name = None
    q_piv['Total'] = q_piv.drop(columns=['Queue Name']).sum(axis=1)
    q_piv = q_piv.sort_values('Total', ascending=False)

    a_piv = pd.pivot_table(mail_df, values='#', index='Agent', columns='Queue Type', aggfunc='count', fill_value=0).reset_index()
    a_piv.columns.name = None
    a_piv['Total'] = a_piv.drop(columns=['Agent']).sum(axis=1)
    a_piv = a_piv.sort_values('Total', ascending=False)

    b_piv = pd.pivot_table(mail_df, values='#', index='Bifurcation', columns='Queue Type', aggfunc='count', fill_value=0).reset_index()
    b_piv.columns.name = None
    b_piv['Total'] = b_piv.drop(columns=['Bifurcation']).sum(axis=1)
    b_piv = b_piv.sort_values('Total', ascending=False)

    sla_data = [
        ['Assign Time SLA',
         (mail_df['Assign Time SLA'] == 'ACHIEVED').sum(),
         (mail_df['Assign Time SLA'] == 'BREACHED').sum()],
        ['First Response SLA',
         (mail_df['First Resonse SLA'] == 'ACHIEVED').sum(),
         (mail_df['First Resonse SLA'] == 'BREACHED').sum()],
        ['Resolve Time SLA',
         (mail_df['Resolve Time SLA'] == 'ACHIEVED').sum(),
         (mail_df['Resolve Time SLA'] == 'BREACHED').sum()],
    ]
    sla_df = pd.DataFrame(sla_data, columns=['SLA Type', 'Achieved', 'Breached'])
    sla_df['Total'] = sla_df['Achieved'] + sla_df['Breached']
    sla_df['Breach %'] = (sla_df['Breached'] / sla_df['Total'].replace(0, np.nan) * 100).round(1)

    def df_to_html(df):
        rows = ""
        for _, row in df.iterrows():
            cells = f'<td class="label">{row.iloc[0]}</td>'
            for v in row.iloc[1:]:
                if isinstance(v, float) and v == int(v):
                    v = int(v)
                cells += f'<td class="num">{v}</td>'
            rows += f'<tr>{cells}</tr>'
        headers = ''.join(f'<th>{c}</th>' for c in df.columns)
        return f'<table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'

    breach_pct = round(stats['sla_first_resp_breached'] / max(stats['total_incoming'], 1) * 100, 1)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Mail Report - {date_str}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'DM Sans', sans-serif; background: #fff; color: #1a1d2e; font-size: 11px; }}
  .header {{ background: #0f3460; color: #fff; padding: 18px 24px; margin-bottom: 20px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ font-size: 18px; font-weight: 700; }}
  .header .meta {{ font-size: 11px; color: #8891aa; text-align: right; }}
  .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }}
  .metric {{ background: #f7f8fc; border: 1px solid #e0e3ed; border-radius: 6px; padding: 12px 14px; text-align: center; }}
  .metric .val {{ font-size: 26px; font-weight: 700; color: #1a1d2e; font-family: 'DM Mono', monospace; }}
  .metric .lbl {{ font-size: 9px; color: #6b7494; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; margin-top: 3px; }}
  .metric .sub {{ font-size: 10px; color: #0f3460; font-family: 'DM Mono', monospace; margin-top: 2px; font-weight: 500; }}
  .warn {{ color: #c0392b; }}
  .section {{ margin-bottom: 22px; break-inside: avoid; }}
  .section-title {{ font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: #0f3460; margin-bottom: 8px; padding-bottom: 5px; border-bottom: 1.5px solid #e0e3ed; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{ background: #f0f2f8; color: #6b7494; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.7px; padding: 7px 10px; text-align: left; border-bottom: 1.5px solid #d0d4e8; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #f0f2f8; color: #2d3150; }}
  td.label {{ font-weight: 500; }}
  td.num {{ text-align: right; font-family: 'DM Mono', monospace; }}
  .footer {{ text-align: center; font-size: 9px; color: #8891aa; margin-top: 20px; padding-top: 10px; border-top: 1px solid #e0e3ed; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>NSEIT Helpdesk - Mail Report</h1>
    <div style="font-size:11px;color:#8891aa;margin-top:3px;">Incoming Mail Analysis | {stats['total_incoming']} tickets processed</div>
  </div>
  <div class="meta">
    <div style="font-size:13px;font-weight:600;color:#fff;">{date_str}</div>
    <div>Auto-generated report</div>
  </div>
</div>

<div class="metrics">
  <div class="metric"><div class="val">{stats['total_incoming']}</div><div class="lbl">Total Mails</div><div class="sub">Closed tickets</div></div>
  <div class="metric"><div class="val">{stats['core']}</div><div class="lbl">Core</div><div class="sub">{round(stats['core']/max(stats['total_incoming'],1)*100,1)}% of total</div></div>
  <div class="metric"><div class="val">{stats['gateway']}</div><div class="lbl">Gateway</div><div class="sub">{round(stats['gateway']/max(stats['total_incoming'],1)*100,1)}% of total</div></div>
  <div class="metric"><div class="val" style="color:#c0392b">{breach_pct}%</div><div class="lbl">1st Response Breach</div><div class="sub">{stats['sla_first_resp_breached']} tickets</div></div>
</div>

<div class="two-col">
  <div class="section">
    <div class="section-title">Queue Summary</div>
    {df_to_html(q_piv)}
  </div>
  <div class="section">
    <div class="section-title">SLA Performance</div>
    {df_to_html(sla_df)}
  </div>
</div>

<div class="section">
  <div class="section-title">Agentwise Mail Count</div>
  {df_to_html(a_piv)}
</div>

<div class="section">
  <div class="section-title">Mail Bifurcation - Categories</div>
  {df_to_html(b_piv)}
</div>

<div class="footer">NSEIT Helpdesk Dashboard | {date_str} | This report is auto-generated. Do not edit manually.</div>
</body></html>"""

    return html


# ─────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────

st.markdown("""
<div class="main-header">
  <h1>DEXIT Global Helpdesk Operations Dashboard</h1>
  <p>Upload raw data files to generate pivot reports. All processing runs automatically.</p>
</div>
""", unsafe_allow_html=True)

tab_calls, tab_mails = st.tabs(["Call Reports", "Mail Reports"])


# ═══════════════════════════════════════════════
# TAB 1: CALLS
# ═══════════════════════════════════════════════
with tab_calls:
    st.markdown('<div class="section-title">Upload Files</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        acd_file = st.file_uploader("ACD Call Details (.csv)", type=["csv"], key="acd")
    with c2:
        call_hist_file = st.file_uploader("Call History (.csv)", type=["csv"], key="ch")
    with c3:
        calls_cat_file = st.file_uploader("Calls Category (.xlsx)", type=["xlsx"], key="cc")

    files_ready = all([acd_file, call_hist_file, calls_cat_file])

    if not files_ready:
        missing = []
        if not acd_file: missing.append("ACD Call Details")
        if not call_hist_file: missing.append("Call History")
        if not calls_cat_file: missing.append("Calls Category")
        st.markdown(f'<div class="alert-warn">Waiting for: {", ".join(missing)}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="info-box">All files uploaded. Running pipeline...</div>', unsafe_allow_html=True)

        with st.spinner("Processing call data..."):
            try:
                call_working, bif, stats = run_calls_pipeline(acd_file, call_hist_file, calls_cat_file)
            except Exception as e:
                st.error(f"Pipeline error: {e}")
                st.stop()

        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

        # Metrics row
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        with m1:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["raw_total"]}</div><div class="metric-label">Raw Input</div></div>', unsafe_allow_html=True)
        with m2:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["after_filter"]}</div><div class="metric-label">After Filter</div></div>', unsafe_allow_html=True)
        with m3:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["answered"]}</div><div class="metric-label">Answered</div><div class="metric-sub">{round(stats["answered"]/stats["after_filter"]*100,1)}%</div></div>', unsafe_allow_html=True)
        with m4:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["hungup"]}</div><div class="metric-label">Abandoned</div><div class="metric-sub">{round(stats["hungup"]/stats["after_filter"]*100,1)}%</div></div>', unsafe_allow_html=True)
        with m5:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["callbacks"]}</div><div class="metric-label">Callbacks Done</div></div>', unsafe_allow_html=True)
        with m6:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["core"]}/{stats["gateway"]}</div><div class="metric-label">Core / Gateway</div></div>', unsafe_allow_html=True)

        st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

        # Project overall
        st.markdown('<h3 class="sub-section">Overall Call Count by Project</h3>', unsafe_allow_html=True)
        proj_df = call_working['Project Name'].value_counts().reset_index()
        proj_df.columns = ['Project Name', 'Total']
        proj_df['%'] = (proj_df['Total'] / proj_df['Total'].sum() * 100).round(1).astype(str) + '%'
        st.dataframe(proj_df, use_container_width=False, hide_index=True)

        # Core + Gateway queue pivots
        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown('<h3 class="sub-section">Core Projectwise Call Count</h3>', unsafe_allow_html=True)
            core_data = call_working[call_working['Project Name'] == 'Core']
            if len(core_data):
                core_piv = pd.pivot_table(core_data, values='#', index='Queue Name1', columns='Answered/Hungup', aggfunc='count', fill_value=0)
                if 'HUNGUP' not in core_piv.columns: core_piv['HUNGUP'] = 0
                if 'ANSWERED' not in core_piv.columns: core_piv['ANSWERED'] = 0
                core_piv['Total'] = core_piv['ANSWERED'] + core_piv['HUNGUP']
                core_piv['Abandon %'] = (core_piv['HUNGUP'] / core_piv['Total'].replace(0, np.nan) * 100).round(1)
                core_piv = core_piv.reset_index().rename(columns={'Queue Name1': 'Queue'})
                total_row = pd.DataFrame([{
                    'Queue': 'Grand Total',
                    'ANSWERED': core_piv['ANSWERED'].sum(),
                    'HUNGUP': core_piv['HUNGUP'].sum(),
                    'Total': core_piv['Total'].sum(),
                    'Abandon %': round(core_piv['HUNGUP'].sum() / core_piv['Total'].sum() * 100, 1)
                }])
                core_display = pd.concat([core_piv, total_row], ignore_index=True)
                st.dataframe(core_display, use_container_width=True, hide_index=True)

        with col_right:
            st.markdown('<h3 class="sub-section">Gateway Projectwise Call Count</h3>', unsafe_allow_html=True)
            gw_data = call_working[call_working['Project Name'] == 'Gateway']
            if len(gw_data):
                gw_piv = pd.pivot_table(gw_data, values='#', index='Queue Name1', columns='Answered/Hungup', aggfunc='count', fill_value=0)
                if 'HUNGUP' not in gw_piv.columns: gw_piv['HUNGUP'] = 0
                if 'ANSWERED' not in gw_piv.columns: gw_piv['ANSWERED'] = 0
                gw_piv['Total'] = gw_piv['ANSWERED'] + gw_piv['HUNGUP']
                gw_piv['Abandon %'] = (gw_piv['HUNGUP'] / gw_piv['Total'].replace(0, np.nan) * 100).round(1)
                gw_piv = gw_piv.reset_index().rename(columns={'Queue Name1': 'Queue'})
                total_row_gw = pd.DataFrame([{
                    'Queue': 'Grand Total',
                    'ANSWERED': gw_piv['ANSWERED'].sum(),
                    'HUNGUP': gw_piv['HUNGUP'].sum(),
                    'Total': gw_piv['Total'].sum(),
                    'Abandon %': round(gw_piv['HUNGUP'].sum() / gw_piv['Total'].sum() * 100, 1)
                }])
                gw_display = pd.concat([gw_piv, total_row_gw], ignore_index=True)
                st.dataframe(gw_display, use_container_width=True, hide_index=True)

        # Agent pivot
        st.markdown('<h3 class="sub-section">Agentwise Call Count</h3>', unsafe_allow_html=True)
        agent_piv = pd.pivot_table(call_working, values='#', index='Username', columns='Project Name', aggfunc='count', fill_value=0)
        agent_piv.columns.name = None
        agent_piv['Grand Total'] = agent_piv.sum(axis=1)
        agent_piv = agent_piv.sort_values('Grand Total', ascending=False).reset_index()
        total_row_ag = {col: agent_piv[col].sum() if col != 'Username' else 'Grand Total' for col in agent_piv.columns}
        agent_display = pd.concat([agent_piv, pd.DataFrame([total_row_ag])], ignore_index=True)
        st.dataframe(agent_display, use_container_width=True, hide_index=True)

        # Call bifurcation
        st.markdown('<h3 class="sub-section">Call Bifurcation - Types of Queries</h3>', unsafe_allow_html=True)
        if stats['bifurcation_unmatched'] > 0:
            st.markdown(f'<div class="alert-warn">{stats["bifurcation_unmatched"]} calls have no category match. Check unmatched disposition codes in the raw data.</div>', unsafe_allow_html=True)

        bif_display = bif[bif['Types of Queries'].notna()].copy()
        tq_piv = pd.pivot_table(bif_display, values='#', index='Types of Queries', columns='Project Name', aggfunc='count', fill_value=0)
        tq_piv.columns.name = None
        tq_piv['Grand Total'] = tq_piv.sum(axis=1)
        tq_piv = tq_piv.sort_values('Grand Total', ascending=False).reset_index()
        total_row_tq = {col: tq_piv[col].sum() if col != 'Types of Queries' else 'Grand Total' for col in tq_piv.columns}
        tq_display = pd.concat([tq_piv, pd.DataFrame([total_row_tq])], ignore_index=True)
        st.dataframe(tq_display, use_container_width=True, hide_index=True)

        # Unmatched
        unmatched = bif[bif['Types of Queries'].isna()]
        if len(unmatched):
            st.markdown('<h3 class="sub-section">Unmatched Disposition Codes (no category)</h3>', unsafe_allow_html=True)
            unmatched_summary = unmatched['User Disposition Code'].value_counts().reset_index()
            unmatched_summary.columns = ['Disposition Code', 'Count']
            st.dataframe(unmatched_summary, use_container_width=False, hide_index=True)

        # Downloads
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        st.markdown('<div class="section-title">Downloads</div>', unsafe_allow_html=True)

        dl1, dl2 = st.columns(2)

        with dl1:
            excel_data = build_excel_calls(call_working, bif)
            st.download_button(
                label="Download Excel Report",
                data=excel_data,
                file_name=f"Call_Report_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        with dl2:
            html_report = build_html_report_calls(call_working, bif, stats)
            st.download_button(
                label="Download HTML Report (A4 / PDF-ready)",
                data=html_report.encode('utf-8'),
                file_name=f"Call_Report_{date.today().strftime('%Y%m%d')}.html",
                mime="text/html",
                use_container_width=True
            )


# ═══════════════════════════════════════════════
# TAB 2: MAILS
# ═══════════════════════════════════════════════
with tab_mails:
    st.markdown('<div class="section-title">Upload Files</div>', unsafe_allow_html=True)

    mc1, mc2 = st.columns(2)
    with mc1:
        mail_file = st.file_uploader("Closed Mails (.xlsx)", type=["xlsx"], key="mf")
    with mc2:
        mail_cat_file = st.file_uploader("Mail Category (.xlsx)", type=["xlsx"], key="mc")

    mail_files_ready = all([mail_file, mail_cat_file])

    if not mail_files_ready:
        missing_m = []
        if not mail_file: missing_m.append("Closed Mails (Int_Mails_Closed.xlsx)")
        if not mail_cat_file: missing_m.append("Mail Category")
        st.markdown(f'<div class="alert-warn">Waiting for: {", ".join(missing_m)}</div>', unsafe_allow_html=True)
    else:
        # First pass: detect available dates
        with st.spinner("Reading dates from mail file..."):
            try:
                _, _, available_dates = run_mails_pipeline(mail_file, mail_cat_file, selected_date=None)
                mail_file.seek(0)
                mail_cat_file.seek(0)
            except Exception as e:
                st.error(f"Error reading mail file: {e}")
                st.stop()

        if not available_dates:
            st.error("No valid closed dates found in the mail file.")
            st.stop()

        date_options = {str(d): d for d in available_dates}
        selected_date_str = st.selectbox(
            "Select date to analyse",
            options=list(date_options.keys()),
            index=len(date_options) - 1,
            key="mail_date"
        )
        selected_date = date_options[selected_date_str]

        with st.spinner(f"Processing mails for {selected_date_str}..."):
            try:
                mail_file.seek(0)
                mail_cat_file.seek(0)
                mail_df, stats, _ = run_mails_pipeline(mail_file, mail_cat_file, selected_date=selected_date)
            except Exception as e:
                st.error(f"Pipeline error: {e}")
                st.stop()

        if len(mail_df) == 0:
            st.warning(f"No closed mails found for {selected_date_str}.")
            st.stop()

        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

        # Metrics
        mm1, mm2, mm3, mm4, mm5 = st.columns(5)
        with mm1:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["total_incoming"]}</div><div class="metric-label">Total Mails</div></div>', unsafe_allow_html=True)
        with mm2:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["core"]}</div><div class="metric-label">Core</div></div>', unsafe_allow_html=True)
        with mm3:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["gateway"]}</div><div class="metric-label">Gateway</div></div>', unsafe_allow_html=True)
        with mm4:
            breach_rate = round(stats['sla_first_resp_breached'] / max(stats['total_incoming'], 1) * 100, 1)
            color = "style='color:#ff6b6b'" if breach_rate > 50 else ""
            st.markdown(f'<div class="metric-card"><div class="metric-value" {color}>{breach_rate}%</div><div class="metric-label">1st Response Breach</div></div>', unsafe_allow_html=True)
        with mm5:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{stats["bulk_closure"]}</div><div class="metric-label">Bulk/No Tag/Blank</div></div>', unsafe_allow_html=True)

        st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

        # SLA summary
        st.markdown('<h3 class="sub-section">SLA Performance</h3>', unsafe_allow_html=True)
        sla_rows = []
        for sla_col, label in [('Assign Time SLA', 'Assign Time'), ('First Resonse SLA', 'First Response'), ('Resolve Time SLA', 'Resolve Time')]:
            achieved = (mail_df[sla_col] == 'ACHIEVED').sum()
            breached = (mail_df[sla_col] == 'BREACHED').sum()
            total = achieved + breached
            breach_pct = round(breached / max(total, 1) * 100, 1)
            sla_rows.append({'SLA Type': label, 'Achieved': achieved, 'Breached': breached, 'Total': total, 'Breach %': f'{breach_pct}%'})
        st.dataframe(pd.DataFrame(sla_rows), use_container_width=False, hide_index=True)

        # Queue pivot
        st.markdown('<h3 class="sub-section">Queue Summary</h3>', unsafe_allow_html=True)
        q_piv = pd.pivot_table(mail_df, values='#', index='Queue Name', columns='Queue Type', aggfunc='count', fill_value=0)
        q_piv.columns.name = None
        q_piv['Grand Total'] = q_piv.sum(axis=1)
        q_piv = q_piv.sort_values('Grand Total', ascending=False).reset_index()
        total_row_q = {col: q_piv[col].sum() if col != 'Queue Name' else 'Grand Total' for col in q_piv.columns}
        q_display = pd.concat([q_piv, pd.DataFrame([total_row_q])], ignore_index=True)
        st.dataframe(q_display, use_container_width=True, hide_index=True)

        # Agent pivot
        st.markdown('<h3 class="sub-section">Agentwise Mail Count</h3>', unsafe_allow_html=True)
        a_piv = pd.pivot_table(mail_df, values='#', index='Agent', columns='Queue Type', aggfunc='count', fill_value=0)
        a_piv.columns.name = None
        a_piv['Grand Total'] = a_piv.sum(axis=1)
        a_piv = a_piv.sort_values('Grand Total', ascending=False).reset_index()
        total_row_a = {col: a_piv[col].sum() if col != 'Agent' else 'Grand Total' for col in a_piv.columns}
        a_display = pd.concat([a_piv, pd.DataFrame([total_row_a])], ignore_index=True)
        st.dataframe(a_display, use_container_width=True, hide_index=True)

        # Bifurcation
        st.markdown('<h3 class="sub-section">Mail Bifurcation - Categories</h3>', unsafe_allow_html=True)
        b_piv = pd.pivot_table(mail_df, values='#', index='Bifurcation', columns='Queue Type', aggfunc='count', fill_value=0)
        b_piv.columns.name = None
        b_piv['Grand Total'] = b_piv.sum(axis=1)
        b_piv = b_piv.sort_values('Grand Total', ascending=False).reset_index()
        total_row_b = {col: b_piv[col].sum() if col != 'Bifurcation' else 'Grand Total' for col in b_piv.columns}
        b_display = pd.concat([b_piv, pd.DataFrame([total_row_b])], ignore_index=True)
        st.dataframe(b_display, use_container_width=True, hide_index=True)

        if stats['unknown'] > 0:
            st.markdown(f'<div class="alert-warn">{stats["unknown"]} mails have unmatched Client Type values not in the category master. Add them to mail_category.xlsx.</div>', unsafe_allow_html=True)

        # Downloads
        st.markdown("<hr class='divider'>", unsafe_allow_html=True)
        st.markdown('<div class="section-title">Downloads</div>', unsafe_allow_html=True)

        mdl1, mdl2 = st.columns(2)

        with mdl1:
            mail_file.seek(0)
            mail_cat_file.seek(0)
            _, _, _ = run_mails_pipeline(mail_file, mail_cat_file, selected_date=selected_date)
            mail_file.seek(0)
            mail_cat_file.seek(0)
            mail_df_dl, _, _ = run_mails_pipeline(mail_file, mail_cat_file, selected_date=selected_date)
            excel_mail = build_excel_mails(mail_df_dl)
            st.download_button(
                label="Download Excel Report",
                data=excel_mail,
                file_name=f"Mail_Report_{selected_date.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        with mdl2:
            html_mail = build_html_report_mails(mail_df, stats, selected_date=selected_date)
            st.download_button(
                label="Download HTML Report (A4 / PDF-ready)",
                data=html_mail.encode('utf-8'),
                file_name=f"Mail_Report_{selected_date.strftime('%Y%m%d')}.html",
                mime="text/html",
                use_container_width=True
            )