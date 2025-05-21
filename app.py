import os
import time
import pandas as pd
from lxml import html
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import plotly.graph_objs as go
from plotly.offline import plot
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, send_file, Response)
from werkzeug.security import generate_password_hash, check_password_hash

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_very_secret_key_here_12345_CHANGE_ME'

# --- Configuration & Directories ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
PAGE_DIR = os.path.join(RESULTS_DIR, 'page')
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads") # For Selenium browser download prefs

os.makedirs(PAGE_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- Simple In-Memory User Store ---
users = {}

# --- Selenium Chrome Options ---
chrome_options = webdriver.ChromeOptions()
prefs = {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "profile.default_content_settings.popups": 0,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
}
chrome_options.add_experimental_option("prefs", prefs)
# To run headless (without opening a visible browser window):
# chrome_options.add_argument("--headless")
# chrome_options.add_argument("--disable-gpu")
# chrome_options.add_argument("--window-size=1920,1080")


# --- Authentication Routes (Identical to previous, assuming they work) ---
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def user_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user_data = users.get(username)
        if user_data and check_password_hash(user_data['hash'], password):
            session['username'] = username
            session['firstname'] = user_data.get('firstname', '')
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        firstname = request.form.get('firstname')
        lastname = request.form.get('lastname')
        email = request.form.get('email')
        password = request.form.get('password')
        password2 = request.form.get('password2')

        if username in users:
            flash('Username already exists', 'error')
        elif password != password2:
            flash('Passwords do not match', 'error')
        else:
            hashed_password = generate_password_hash(password)
            users[username] = {'hash': hashed_password, 'firstname': firstname, 'lastname': lastname}
            flash('Signup successful! Please log in.', 'success')
            return redirect(url_for('user_login'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('firstname', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('user_login'))

def is_logged_in():
    return 'username' in session

# --- Core Application Routes ---
@app.route('/home')
def home():
    if not is_logged_in():
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('user_login'))
    return render_template('home.html', firstname=session.get('firstname'))

@app.route('/check')
def check_page(): # Renamed to avoid conflict with built-in 'check'
    if not is_logged_in():
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('user_login'))
    return render_template('check.html')

@app.route('/run_check_and_combine', methods=['POST'])
def run_check_and_combine():
    if not is_logged_in():
        flash('Please log in to perform this action.', 'warning')
        return redirect(url_for('user_login'))

    usn_input = request.form.get('student_ids', '')
    usn_list = [usn.strip() for usn in usn_input.split(',') if usn.strip()]

    if not usn_list:
        flash('Please enter at least one valid USN.', 'error')
        return redirect(url_for('check_page'))

    print(f"Processing USNs: {usn_list}")
    saved_html_count = 0

    for usn in usn_list:
        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.implicitly_wait(10) # Increased implicit wait
            driver.get('https://results.vtu.ac.in/DJcbcs24/index.php') # Target URL

            WebDriverWait(driver, 20).until(
                EC.visibility_of_element_located((By.NAME, 'lns'))
            ).send_keys(usn)

            print(f"ACTION REQUIRED: Enter captcha for USN: {usn} in the browser within 20 seconds.")
            # Wait for submit button to be present, user has time to enter captcha
            submit_button_locator = (By.ID, 'submit')
            WebDriverWait(driver, 20).until(EC.presence_of_element_located(submit_button_locator))
            time.sleep(20) # Explicit pause for manual CAPTCHA entry

            # Attempt to click submit
            # Add a check to see if the captcha was accepted or if it's still the same page
            current_url_before_submit = driver.current_url
            driver.find_element(*submit_button_locator).click()
            
            # Wait for page to potentially change or load results
            time.sleep(7) # Increased wait after submit

            # Check if URL changed or if a known results element is present
            # This is a more robust check than just "Invalid USN" in page source
            content = driver.page_source
            
            # --- MORE ROBUST CHECK FOR RESULTS PAGE ---
            # Look for a unique element that ONLY appears on the results page.
            # Example: A table with a specific ID or class, or a specific heading.
            # For now, we'll stick to the content check, but this is where you'd refine.
            # You can also check if the URL changed significantly away from the index page.
            if "Invalid USN" in content or \
               "Results are not yet available" in content or \
               "Please enter valid captcha" in content or \
               driver.current_url == current_url_before_submit: # If URL didn't change, likely captcha failed
                print(f"No results, invalid USN, or CAPTCHA issue for {usn}. Page source might be the form page.")
                # Optionally save this "failed" page for debugging what Selenium sees
                # with open(os.path.join(PAGE_DIR, f'failed_page_{usn}.html'), 'w', encoding='utf-8') as fp:
                #     fp.write(content)
                continue

            html_file_path = os.path.join(PAGE_DIR, f'page_{usn}.html')
            with open(html_file_path, 'w', encoding='utf-8') as fp:
                fp.write(content)
            print(f"SUCCESS: Saved HTML for USN: {usn} to {html_file_path}")
            saved_html_count += 1

        except Exception as e:
            print(f"ERROR processing USN {usn}: {str(e)}")
            flash(f'An error occurred while processing USN {usn}. Check console logs.', 'error')
        finally:
            if driver:
                driver.quit()

    if saved_html_count == 0:
        flash('No result pages were successfully downloaded. Please check USNs and CAPTCHA entries.', 'warning')
        return redirect(url_for('check_page'))

    print("Starting data parsing and Excel generation...")
    html_files = [f for f in os.listdir(PAGE_DIR) if f.startswith('page_') and f.endswith('.html')]

    if not html_files: # Should be caught by saved_html_count, but defensive check
         flash('Critical Error: No HTML files found in page directory after scraping.', 'error')
         return redirect(url_for('check_page'))

    data = {}
    all_subjects_set = set()

    for html_filename in html_files:
        usn_from_file = html_filename.replace('page_', '').replace('.html', '')
        file_path = os.path.join(PAGE_DIR, html_filename)
        print(f"\n--- Parsing file: {html_filename} for USN: {usn_from_file} ---")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                print(f"WARNING: File {html_filename} is empty.")
                continue

            tree = html.fromstring(content)

            # --- !!! CRITICAL XPATH ADJUSTMENT AREA !!! ---
            # The XPaths below are educated guesses based on common structures and your previous code.
            # You MUST verify and adjust these by inspecting a SAVED `page_{usn}.html`
            # file that you KNOW contains valid student results.

            # Attempt 1: Using the divTableRow/divTableCell structure (from original report)
            # This assumes a relatively flat structure of div "rows" and "cells".
            # Modify if VTU page has a more nested table or different class names.
            
            # Find a container that holds all the result rows. This is often a good starting point.
            # Example: Look for a div with a specific ID like 'resultTable' or a unique class.
            # If no obvious overall container, start with rows.
            
            # More specific XPath for rows, assuming they are under a known structure
            # This is a common pattern: a main content div, then table-like divs
            # You need to find the unique parent of the result rows.
            # Let's try finding a prominent table-like structure first
            
            # Option A: Look for a <table> element if one exists
            result_table_element = tree.xpath('//table[contains(@class,"table")] | //table[@id="resultsTable"]') # Common table classes/IDs
            
            subjects_list = []
            marks_list = []

            if result_table_element:
                print(f"Found <table> element for {usn_from_file}. Parsing using table structure.")
                # Assuming standard <tr> for rows and <td> for cells within the found table
                # Adjust td indices based on actual columns for subject code and external marks
                # Example: td[1] for first column, td[5] for fifth.
                # This also assumes subject codes and marks are direct text or within a simple tag like <b>
                # Skip header row(s) if necessary (e.g., by checking content or using `tr[position()>1]`)
                # rows_in_table = result_table_element[0].xpath('.//tr[.//td[1] and .//td[5]]') # Rows with at least 5 tds
                rows_in_table = result_table_element[0].xpath('.//tr')
                print(f"Found {len(rows_in_table)} <tr> in table for {usn_from_file}.")
                for i, row_node in enumerate(rows_in_table):
                    # Get all td texts to inspect
                    cells = row_node.xpath('.//td/descendant-or-self::*/text()') # Get all text from TDs
                    # Heuristic: a valid data row will have multiple cells. Header rows might too.
                    # Need to identify which `td` contains subject and which contains marks.
                    # Let's assume subject is in the first few cells, and marks are later.
                    # This is VERY DEPENDENT on the table structure.
                    # Example: Subject Code typically in td[1] or td[2], External Marks in td[5] or td[6]
                    
                    # You need to check the number of cells and identify by position or content
                    td_elements = row_node.xpath('.//td')
                    if len(td_elements) > 4: # Assuming at least 5 columns for a valid data row
                        try:
                            # Try to extract text robustly, stripping whitespace
                            # Adjust indices [0] for 1st td, [4] for 5th td (0-indexed)
                            subject_code_texts = td_elements[1].xpath('.//text()') # Get all text within the 2nd td
                            subject_code = " ".join([s.strip() for s in subject_code_texts if s.strip()])

                            # External marks usually in a later column
                            external_mark_texts = td_elements[4].xpath('.//text()') # Get all text within the 5th td
                            external_mark = "".join([m.strip() for m in external_mark_texts if m.strip().isdigit() or m.strip() == 'AB' or m.strip() == 'NE']) # Filter for digits or common non-numeric marks
                            
                            # Basic validation: subject code should not be empty, marks should be plausible
                            if subject_code and (external_mark.isdigit() or external_mark in ['AB', 'NE', 'ABSENT', 'FAIL', 'PASS']): # Add more valid non-numeric marks
                                # Further check: subject code shouldn't look like a header
                                if subject_code.lower() not in ["subject code", "subject name", "subject", "sl. no."]:
                                    subjects_list.append(subject_code)
                                    marks_list.append(external_mark)
                                    print(f"  TABLE PARSED Row {i}: Subject='{subject_code}', Mark='{external_mark}'")
                                else:
                                    print(f"  Skipping potential header row in table: '{subject_code}'")
                            # else:
                                # print(f"  Skipping row {i} in table due to invalid subject/mark: Sub='{subject_code}', Mark='{external_mark}'")
                        except IndexError:
                            # print(f"  IndexError on row {i} in table (likely not a data row or unexpected structure). Cells: {len(td_elements)}")
                            pass # Common for header/footer rows in tables
                    # else:
                        # print(f"  Skipping row {i} in table (not enough cells: {len(td_elements)})")


            # Option B: Fallback to divTableRow/divTableCell if no <table> was found or parsed successfully
            if not subjects_list: # If table parsing didn't yield results
                print(f"No <table> parsed or no data from table for {usn_from_file}. Trying div structure...")
                # This XPath assumes 'divTableRow' are direct children of some container.
                # It might be better to find a specific parent div first.
                # Example: `//div[@id='resultsContainer']//div[contains(@class, "divTableRow")]`
                div_rows = tree.xpath('//div[contains(@class, "divTableRow")]')
                print(f"Found {len(div_rows)} 'divTableRow' elements for {usn_from_file}.")
                
                for i, row_node in enumerate(div_rows):
                    # Check if this "row" looks like a header (e.g., contains "Subject Code", "Marks")
                    header_check_texts = "".join(row_node.xpath('.//div[contains(@class,"divTableCell")]//text()')).lower()
                    if "subject code" in header_check_texts or "internal marks" in header_check_texts:
                        print(f"  Skipping potential header divRow: {header_check_texts[:50]}...")
                        continue

                    try:
                        # Adjust indices [1] and [5] based on actual cell order.
                        # Using descendant-or-self::* to get text from any nested tags.
                        subject_code_texts = row_node.xpath('.//div[contains(@class,"divTableCell")][1]/descendant-or-self::*/text()')
                        subject_code = " ".join([s.strip() for s in subject_code_texts if s.strip()])

                        external_mark_texts = row_node.xpath('.//div[contains(@class,"divTableCell")][5]/descendant-or-self::*/text()')
                        # Be careful with stripping, ensure 'AB' or other text marks are preserved if needed
                        external_mark = "".join([m.strip() for m in external_mark_texts if m.strip().isdigit() or m.strip() in ['AB', 'NE']])


                        if subject_code and (external_mark.isdigit() or external_mark in ['AB', 'NE']):
                            subjects_list.append(subject_code)
                            marks_list.append(external_mark)
                            print(f"  DIV PARSED Row {i}: Subject='{subject_code}', Mark='{external_mark}'")
                        # else:
                            # print(f"  Skipping divRow {i} due to invalid subject/mark: Sub='{subject_code}', Mark='{external_mark}'")
                    except IndexError:
                        # print(f"  IndexError on divRow {i} (likely not a data row or unexpected structure).")
                        pass # This can happen for non-data divs styled as rows

            if subjects_list and marks_list:
                data[usn_from_file] = dict(zip(subjects_list, marks_list))
                all_subjects_set.update(subjects_list)
                print(f"SUCCESS: Parsed {len(subjects_list)} subjects for USN: {usn_from_file}")
            else:
                print(f"FAILURE: No subject/mark data extracted from {html_filename} for USN: {usn_from_file}")

        except Exception as e:
            print(f"CRITICAL ERROR parsing file {html_filename}: {str(e)}")
            import traceback
            traceback.print_exc()


    if not data:
        flash('Could not parse data from any downloaded files. Check console for parsing details and verify saved HTMLs.', 'error')
        return redirect(url_for('check_page'))

    # Create DataFrame
    all_subjects_sorted = sorted(list(all_subjects_set))
    df_data = []
    for usn_key, marks_dict in data.items():
        row = {'USN': usn_key}
        for subj in all_subjects_sorted:
            row[subj] = marks_dict.get(subj, '-') # Use '-' for missing subjects for a student
        df_data.append(row)

    if not df_data:
        flash('Data dictionary was populated but DataFrame could not be constructed. Check parsing logic.', 'error')
        return redirect(url_for('check_page'))

    df = pd.DataFrame(df_data)
    # Ensure USN is the first column, followed by sorted subjects
    df = df[['USN'] + all_subjects_sorted]


    excel_file_path = os.path.join(PAGE_DIR, 'results_table.xlsx')
    try:
        df.to_excel(excel_file_path, index=False)
        print(f"SUCCESS: Generated Excel file: {excel_file_path}")
        flash('Successfully processed USNs and generated results table.', 'success')
    except Exception as e_excel:
        print(f"ERROR saving Excel file: {str(e_excel)}")
        flash('Error saving results to Excel. Check console.', 'error')
        
    return redirect(url_for('check_page'))


# --- Routes for a5thsem, download_excel, visualize_data (largely same, ensure they use 'check_page' for redirects) ---
@app.route('/a5thsem')
def a5thsem():
    if not is_logged_in():
        flash('Please log in.', 'warning')
        return redirect(url_for('user_login'))

    input_file = os.path.join(PAGE_DIR, 'results_table.xlsx')
    output_file = os.path.join(PAGE_DIR, '5thsem.xlsx')

    if not os.path.exists(input_file):
        flash('results_table.xlsx not found. Run "Check USNs & Generate Excel" first.', 'error')
        return redirect(url_for('check_page'))
    try:
        df = pd.read_excel(input_file)
        # IMPORTANT: Ensure these column names EXACTLY match what's in your results_table.xlsx
        # These are derived from the parsed subject codes.
        selected_columns = ['USN', '21CIV57', '21CS51', '21CS52', '21CS53', 
                              '21CS54', '21CSL55', '21CSL581', '21RMI56'] # Example
        
        actual_columns_in_df = df.columns.tolist()
        print(f"Columns in results_table.xlsx: {actual_columns_in_df}")
        print(f"Columns selected for 5th sem: {selected_columns}")

        # Check for missing columns, provide more specific feedback
        missing_cols = [col for col in selected_columns if col not in actual_columns_in_df]
        if 'USN' not in actual_columns_in_df: # USN must exist
             flash('Critical Error: USN column missing in results_table.xlsx.', 'error')
             return redirect(url_for('check_page'))

        if missing_cols:
            # Only select columns that are actually present, to avoid KeyError
            # But still warn the user about the ones that were expected but not found.
            flash(f"Warning: Some 5th sem columns not found in results: {', '.join(missing_cols)}. Proceeding with available columns.", 'warning')
            # Filter selected_columns to only those that exist in df
            final_selected_columns = [col for col in selected_columns if col in actual_columns_in_df]
            if len(final_selected_columns) <=1 and 'USN' in final_selected_columns : # Only USN or less
                flash(f"Error: No valid subject columns found for 5th sem filtering from: {', '.join(selected_columns)}", 'error')
                return redirect(url_for('check_page'))
        else:
            final_selected_columns = selected_columns

        df_selected = df[final_selected_columns]
        df_selected.to_excel(output_file, index=False)
        print(f"Generated 5th Sem Excel: {output_file}")
        return send_file(output_file, as_attachment=True, download_name='5thsem.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except FileNotFoundError:
        flash('results_table.xlsx not found.', 'error')
        return redirect(url_for('check_page'))
    except KeyError as e_key:
        flash(f"Error: A specified column for 5th sem not found: {str(e_key)}. Check column names.", 'error')
        print(f"KeyError during 5th sem processing: {str(e_key)}")
        return redirect(url_for('check_page'))
    except Exception as e:
        print(f"Error in /a5thsem: {str(e)}")
        flash(f'Error generating 5th sem file: {str(e)}', 'error')
        return redirect(url_for('check_page'))

@app.route('/download_excel')
def download_excel():
    if not is_logged_in():
        flash('Please log in.', 'warning')
        return redirect(url_for('user_login'))
    excel_file_path = os.path.join(PAGE_DIR, 'results_table.xlsx')
    if not os.path.exists(excel_file_path):
        flash('results_table.xlsx not found. Run "Check USNs & Generate Excel" first.', 'error')
        return redirect(url_for('check_page'))
    try:
        return send_file(excel_file_path, as_attachment=True, download_name='results_table.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f'Error downloading Excel: {str(e)}', 'error')
        return redirect(url_for('check_page'))

@app.route('/visualize_data')
def visualize_data():
    if not is_logged_in():
        flash('Please log in.', 'warning')
        return redirect(url_for('user_login'))
    excel_file_path = os.path.join(PAGE_DIR, '5thsem.xlsx') # Assumes 5thsem.xlsx is the target for visualization

    if not os.path.exists(excel_file_path):
        flash('5thsem.xlsx not found. Please generate it first via the "Download 5th Sem Excel" button.', 'error')
        return redirect(url_for('check_page'))
    try:
        df = pd.read_excel(excel_file_path)
        if df.empty:
            flash('5thsem.xlsx is empty or could not be read properly.', 'warning')
            return redirect(url_for('check_page'))
        if 'USN' not in df.columns:
            flash('USN column missing in 5thsem.xlsx for visualization.', 'error')
            return redirect(url_for('check_page'))


        subjects = [col for col in df.columns if col != 'USN']
        if not subjects:
            flash('No subject columns found in 5thsem.xlsx for visualization.', 'error')
            return redirect(url_for('check_page'))


        for col in subjects:
            df[col] = pd.to_numeric(df[col], errors='coerce') # Coerce non-numeric to NaN
        # df.fillna('-', inplace=True) # Replace NaN with '-' for display, or 0 for calculations if preferred

        usns = df['USN'].astype(str).tolist()


        # Line Plot
        fig_line = go.Figure()
        for _, row in df.iterrows():
            valid_marks = row[subjects].dropna() # Only plot subjects with actual (numeric) marks for this student
            if not valid_marks.empty:
                fig_line.add_trace(go.Scatter(x=valid_marks.index, y=valid_marks.values, mode='lines+markers', name=str(row['USN'])))
        fig_line.update_layout(title='Marks Visualization (Line Plot)', xaxis_title='Subjects', yaxis_title='Marks', xaxis={'type': 'category'})
        plot_div_line = plot(fig_line, output_type='div', include_plotlyjs=False)

        # Heatmap (Ensure data_matrix has numeric types)
        # Create a matrix of numeric marks, replacing NaNs if necessary (e.g., with 0 or a special value)
        data_matrix_numeric = df[subjects].fillna(float('nan')).values # Use NaN for heatmap missing values
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=data_matrix_numeric, x=subjects, y=usns, colorscale='Viridis',
            colorbar=dict(title='Marks'), zmin=0, zmax=100,
            hoverongaps=False # Don't show hover for NaN gaps
        ))
        fig_heatmap.update_layout(title='Marks Heatmap', xaxis_title='Subjects', yaxis_title='USN', xaxis={'type': 'category'}, yaxis={'type': 'category', 'autorange': 'reversed'})
        plot_div_heatmap = plot(fig_heatmap, output_type='div', include_plotlyjs=False)

        # Histogram
        fig_hist = go.Figure()
        for subject in subjects:
            valid_marks_subject = df[subject].dropna() # Marks for this subject, NaNs removed
            if not valid_marks_subject.empty:
                fig_hist.add_trace(go.Histogram(x=valid_marks_subject, name=subject, opacity=0.75))
        fig_hist.update_layout(title='Marks Distribution (Histogram)', xaxis_title='Marks', yaxis_title='Frequency', barmode='overlay')
        plot_div_hist = plot(fig_hist, output_type='div', include_plotlyjs=False)

        return render_template('visualize.html',
                               plot_div_line=plot_div_line,
                               plot_div_heatmap=plot_div_heatmap,
                               plot_div_hist=plot_div_hist)
    except FileNotFoundError:
        flash('5thsem.xlsx not found.', 'error')
    except Exception as e:
        print(f"Error in /visualize_data: {str(e)}")
        flash(f'Error visualizing data: {str(e)}. Check console.', 'error')
    return redirect(url_for('check_page'))


# --- Run the App ---
if __name__ == '__main__':
    print("Flask app starting...")
    app.run(debug=True, host='0.0.0.0', port=5001) # Example: run on a different port and accessible on network