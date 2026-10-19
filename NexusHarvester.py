import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
import threading
import requests
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import time
import json
import os
import csv
from datetime import datetime
import pycountry
import webbrowser
import unicodedata
import subprocess
import sys

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".lead_engine_settings.json")
HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".lead_engine_history.json")



def play_completion_chime(sound_name="Glass"):
    """Non-blocking audio completion chime using native OS sound library."""
    def _play():
        try:
            if os.name == 'nt':
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except Exception:
                    pass
            else:
                sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
                if os.path.exists(sound_path):
                    subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    threading.Thread(target=_play, daemon=True).start()


def get_groq_active_models(groq_key):
    """Dynamically returns active, verified text generation models from Groq."""
    priority = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "allam-2-7b"]
    try:
        headers = {"Authorization": f"Bearer {groq_key}"}
        resp = requests.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=4)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            active_ids = [m['id'] for m in data if m.get('active', True)]
            # Filter out non-text, moderation, or audio models
            chat_models = [m for m in active_ids if not any(x in m.lower() for x in ['whisper', 'guard', 'safeguard', 'orpheus-arabic'])]
            # Sort preferred models first
            sorted_models = [p for p in priority if p in chat_models] + [m for m in chat_models if m not in priority]
            if sorted_models:
                return sorted_models
    except Exception:
        pass
    return priority


def normalize_text(s):
    if not s:
        return ""
    # Strip accents / diacritics (e.g. Telangāna -> telangana)
    nfkd = unicodedata.normalize('NFKD', str(s))
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r'[\s,.-]+', ' ', stripped).strip().lower()


def match_country(place_country_long, place_country_short, target_country):
    if not target_country or target_country == "Any":
        return True
    tc = normalize_text(target_country)
    pc_l = normalize_text(place_country_long)
    pc_s = normalize_text(place_country_short)
    if not tc:
        return True
    if tc == pc_l or tc == pc_s or (pc_l and tc in pc_l) or (pc_l and pc_l in tc):
        return True
    # Synonyms for international countries
    synonyms = [
        {"united states", "usa", "us", "u.s.", "u.s.a.", "united states of america"},
        {"united kingdom", "uk", "u.k.", "great britain", "britain", "england", "scotland", "wales"},
        {"united arab emirates", "uae", "u.a.e."},
        {"russian federation", "russia"},
        {"korea, republic of", "south korea", "korea"},
        {"viet nam", "vietnam"},
        {"syrian arab republic", "syria"},
        {"venezuela, bolivarian republic of", "venezuela"},
        {"iran, islamic republic of", "iran"},
        {"bolivia, plurinational state of", "bolivia"},
        {"tanzania, united republic of", "tanzania"}
    ]
    for syn_group in synonyms:
        if tc in syn_group:
            if pc_l in syn_group or pc_s in syn_group:
                return True
    return False


def match_state(place_state_long, place_state_short, full_address, target_state):
    if not target_state or target_state == "Any":
        return True
    ts = normalize_text(target_state)
    if not ts:
        return True
    ps_l = normalize_text(place_state_long)
    ps_s = normalize_text(place_state_short)
    if ts == ps_l or ts == ps_s:
        return True
    if ps_l and (ts in ps_l or ps_l in ts):
        return True
    # Fallback to checking full address
    if full_address and ts in normalize_text(full_address):
        return True
    return False


def match_city(all_address_text, target_city):
    if not target_city:
        return True
    tc = normalize_text(target_city)
    if not tc:
        return True
    return tc in normalize_text(all_address_text)


class AutocompleteCombobox(ttk.Combobox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.completion_list = kwargs.get('values', [])
        self.bind('<KeyRelease>', self.handle_keyrelease)

    def set_completion_list(self, completion_list):
        self.completion_list = completion_list
        self['values'] = self.completion_list

    def handle_keyrelease(self, event):
        if event.keysym in ('Up', 'Down', 'Return', 'Tab', 'Left', 'Right', 'Escape'):
            return
        
        typed = self.get()
        if typed == '':
            self['values'] = self.completion_list
        else:
            filtered = [item for item in self.completion_list if typed.lower() in str(item).lower()]
            self['values'] = filtered
            
        if self['values']:
            self.event_generate('<Down>')

class ScraperTab:

    def __init__(self, parent_app, parent_frame, is_prospector=False):
        self.app = parent_app
        self.frame = parent_frame
        self.is_prospector = is_prospector
        self.is_searching = False
        self.all_selected = False
        
        self.setup_ui()

    def setup_ui(self):
        # ---------------- MAIN CONTAINER ----------------
        main_container = ttk.Frame(self.frame)
        main_container.pack(expand=True, fill='both', padx=20, pady=20)

        # ---------------- SEARCH BAR FRAME ----------------
        search_frame = ttk.Frame(main_container)
        search_frame.pack(fill='x', pady=(0, 15))
        
        lbl = "Target Buyers:" if self.is_prospector else "Target Data:"
        ttk.Label(search_frame, text=lbl, font=("Segoe UI", 12, "bold")).pack(side='left', padx=5)
        
        self.query_entry = ttk.Entry(search_frame, width=40, font=("Segoe UI", 12))
        self.query_entry.pack(side='left', padx=10)
        
        self.search_btn = ttk.Button(search_frame, text="🔍 Start Deep Scrape", command=self.start_search_thread, style="Accent.TButton")
        self.search_btn.pack(side='left', padx=5)
        
        self.cancel_btn = ttk.Button(search_frame, text="🛑 Stop", command=self.stop_search, state=tk.DISABLED, style="Danger.TButton")
        self.cancel_btn.pack(side='left', padx=5)
        
        # ---------------- LOCATION & FILTERS FRAME ----------------
        filters_frame = ttk.LabelFrame(main_container, text=" Extraction Filters ")
        filters_frame.pack(fill='x', pady=(0, 15), ipady=10)
        
        # Row 0: Location Filters
        ttk.Label(filters_frame, text="Country:").grid(row=0, column=0, padx=10, pady=(10,5), sticky='e')
        self.countries = ["Any"] + sorted([c.name for c in pycountry.countries])
        
        # Using autocomplete combobox
        self.filter_country = AutocompleteCombobox(filters_frame, values=self.countries, width=20, font=("Segoe UI", 11))
        self.filter_country.set("Any")
        self.filter_country.grid(row=0, column=1, padx=5, pady=(10,5))
        self.filter_country.bind("<<ComboboxSelected>>", self.on_country_change)
        
        ttk.Label(filters_frame, text="State/Region:").grid(row=0, column=2, padx=10, pady=(10,5), sticky='e')
        self.filter_state = AutocompleteCombobox(filters_frame, values=["Any"], width=20, font=("Segoe UI", 11))
        self.filter_state.set("Any")
        self.filter_state.grid(row=0, column=3, padx=5, pady=(10,5))

        ttk.Label(filters_frame, text="City/District:").grid(row=0, column=4, padx=10, pady=(10,5), sticky='e')
        self.filter_city = ttk.Entry(filters_frame, width=15, font=("Segoe UI", 11))
        self.filter_city.grid(row=0, column=5, padx=5, pady=(10,5))
        
        # Row 1: Ratings & Assets
        ttk.Label(filters_frame, text="Min Rating:").grid(row=1, column=0, padx=10, pady=5, sticky='e')
        vcmd = (self.frame.register(self.validate_rating), '%P')
        self.filter_min_r = ttk.Spinbox(filters_frame, from_=0.0, to=5.0, increment=0.1, width=5, font=("Segoe UI", 11), validate='key', validatecommand=vcmd)
        self.filter_min_r.set(0.0)
        self.filter_min_r.grid(row=1, column=1, padx=5, pady=5, sticky='w')
        
        ttk.Label(filters_frame, text="Max Rating:").grid(row=1, column=2, padx=10, pady=5, sticky='e')
        self.filter_max_r = ttk.Spinbox(filters_frame, from_=0.0, to=5.0, increment=0.1, width=5, font=("Segoe UI", 11), validate='key', validatecommand=vcmd)
        self.filter_max_r.set(5.0)
        self.filter_max_r.grid(row=1, column=3, padx=5, pady=5, sticky='w')
        
        options = ['Ignore', 'Required', 'Missing']
        
        ttk.Label(filters_frame, text="Website:").grid(row=1, column=4, padx=10, pady=5, sticky='e')
        self.filter_website = ttk.Combobox(filters_frame, values=options, state='readonly', width=10, font=("Segoe UI", 11))
        self.filter_website.set("Ignore")
        self.filter_website.grid(row=1, column=5, padx=5, pady=5, sticky='w')
        
        ttk.Label(filters_frame, text="Email:").grid(row=2, column=0, padx=10, pady=(5,10), sticky='e')
        self.filter_email = ttk.Combobox(filters_frame, values=options, state='readonly', width=10, font=("Segoe UI", 11))
        self.filter_email.set("Ignore")
        self.filter_email.grid(row=2, column=1, padx=5, pady=(5,10), sticky='w')

        ttk.Label(filters_frame, text="Any Socials:").grid(row=2, column=2, padx=10, pady=(5,10), sticky='e')
        self.filter_socials = ttk.Combobox(filters_frame, values=options, state='readonly', width=10, font=("Segoe UI", 11))
        self.filter_socials.set("Ignore")
        self.filter_socials.grid(row=2, column=3, padx=5, pady=(5,10), sticky='w')
        
        # ---------------- ACTION BUTTONS ----------------
        action_frame = ttk.Frame(main_container)
        action_frame.pack(fill='x', pady=(0, 8))
        
        self.select_all_btn = ttk.Button(action_frame, text="☑ Select All", command=self.toggle_all)
        self.select_all_btn.pack(side='left', padx=(0,10))
        
        self.export_btn = ttk.Button(action_frame, text="💾 Export to CSV", command=self.export_selected)
        self.export_btn.pack(side='left', padx=10)
        
        self.send_to_mailer_btn = ttk.Button(action_frame, text="🚀 Send to AI Mailer (Tab 3)", command=self.send_to_mailer)
        self.send_to_mailer_btn.pack(side='left', padx=10)

        if self.is_prospector:
            self.email_btn = ttk.Button(action_frame, text="✉️ Email Pitch to Selected", command=self.start_email_thread, style="Accent.TButton")
            self.email_btn.pack(side='left', padx=10)

        # ---------------- LIVE ROI & VALUE BANNER ----------------
        roi_frame = ttk.Frame(main_container)
        roi_frame.pack(fill='x', pady=(0, 10))
        
        self.roi_badge_var = tk.StringVar(value="💰 Value Generated: $0.00 | Apollo SaaS Cost: $0.00 | Your Cost: $0.00 (100% Free)")
        self.roi_badge_lbl = ttk.Label(roi_frame, textvariable=self.roi_badge_var, font=("Segoe UI", 10, "bold"), foreground="#2e7d32")
        self.roi_badge_lbl.pack(side='left')
        
        hint_text = "(Green = Sent)  (Red = Failed)" if self.is_prospector else "(Double-click any link cell to open in browser)"
        ttk.Label(roi_frame, text=hint_text, font=("Segoe UI", 9, "italic")).pack(side='right')

        # ---------------- DATA CONSOLE (TREEVIEW) ----------------
        tree_frame = ttk.Frame(main_container)
        tree_frame.pack(expand=True, fill='both')
        
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient="vertical")
        tree_scroll_y.pack(side='right', fill='y')
        
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal")
        tree_scroll_x.pack(side='bottom', fill='x')
        
        columns = ('Select', 'Name', 'Address', 'City', 'State', 'Country', 'Rating', 'Phone', 'Email', 'Website', 'Facebook', 'Instagram', 'LinkedIn')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings', selectmode='browse', 
                                 yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        
        tree_scroll_y.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)
        
        self.tree.heading('Select', text='[X]')
        self.tree.heading('Name', text='Business Name')
        self.tree.heading('Address', text='Full Address')
        self.tree.heading('City', text='City')
        self.tree.heading('State', text='State')
        self.tree.heading('Country', text='Country')
        self.tree.heading('Rating', text='Rating')
        self.tree.heading('Phone', text='Phone')
        self.tree.heading('Email', text='Email')
        self.tree.heading('Website', text='Website')
        self.tree.heading('Facebook', text='Facebook')
        self.tree.heading('Instagram', text='Instagram')
        self.tree.heading('LinkedIn', text='LinkedIn')
        
        self.tree.column('Select', width=50, anchor='center', stretch=False)
        self.tree.column('Name', width=200, minwidth=150)
        self.tree.column('Address', width=250, minwidth=200)
        self.tree.column('City', width=120, minwidth=100)
        self.tree.column('State', width=120, minwidth=100)
        self.tree.column('Country', width=120, minwidth=100)
        self.tree.column('Rating', width=70, anchor='center', minwidth=60)
        self.tree.column('Phone', width=140, minwidth=120)
        self.tree.column('Email', width=200, minwidth=150)
        self.tree.column('Website', width=250, minwidth=200)
        self.tree.column('Facebook', width=250, minwidth=200)
        self.tree.column('Instagram', width=250, minwidth=200)
        self.tree.column('LinkedIn', width=250, minwidth=200)
        
        self.tree.tag_configure('emailed', foreground='#888888')
        self.tree.tag_configure('success', background='#2e7d32', foreground='white')
        self.tree.tag_configure('fail', background='#c62828', foreground='white')
        
        self.tree.pack(expand=True, fill='both')
        self.tree.bind('<ButtonRelease-1>', self.on_tree_click)
        self.tree.bind('<Double-1>', self.on_tree_double_click)
        
        # Status Bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready.")
        self.status_bar = ttk.Label(self.frame, textvariable=self.status_var, relief=tk.FLAT, anchor=tk.W, font=("Segoe UI", 10))
        self.status_bar.pack(fill='x', side='bottom', padx=20, pady=10)

    def flash_completion(self):
        try:
            self.roi_badge_lbl.config(foreground="#00e676")
            self.status_bar.config(foreground="#00e676")
            def _revert():
                try:
                    self.roi_badge_lbl.config(foreground="#2e7d32")
                    self.status_bar.config(foreground="")
                except Exception:
                    pass
            self.app.root.after(1800, _revert)
        except Exception:
            pass

    def validate_rating(self, P):
        if P == "" or P == ".": return True
        try:
            val = float(P)
            return 0.0 <= val <= 5.0
        except ValueError:
            return False

    def on_country_change(self, event):
        country_name = self.filter_country.get()
        if country_name == "Any" or not country_name:
            self.filter_state.set_completion_list(["Any"])
            self.filter_state.set("Any")
            return
            
        try:
            country = pycountry.countries.get(name=country_name)
            if country:
                subdivisions = pycountry.subdivisions.get(country_code=country.alpha_2)
                if subdivisions:
                    states = sorted([s.name for s in subdivisions])
                    self.filter_state.set_completion_list(["Any"] + states)
                else:
                    self.filter_state.set_completion_list(["Any"])
            else:
                self.filter_state.set_completion_list(["Any"])
        except Exception:
            self.filter_state.set_completion_list(["Any"])
        self.filter_state.set("Any")

    def on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)
            if column == '#1': # Select column
                item = self.tree.identify_row(event.y)
                if item:
                    current = self.tree.set(item, 'Select')
                    new_val = '☐' if current == '☑' else '☑'
                    self.tree.set(item, 'Select', new_val)

    def on_tree_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)
            item = self.tree.identify_row(event.y)
            if not item: return
            
            values = self.tree.item(item, 'values')
            url = ""
            if column == '#10': url = values[9]   # Website
            elif column == '#11': url = values[10] # Facebook
            elif column == '#12': url = values[11] # Instagram
            elif column == '#13': url = values[12] # LinkedIn
            
            if url and str(url).strip().startswith('http'):
                webbrowser.open(str(url).strip())

    def toggle_all(self):
        self.all_selected = not self.all_selected
        new_val = '☑' if self.all_selected else '☐'
        for item in self.tree.get_children():
            self.tree.set(item, 'Select', new_val)
        self.select_all_btn.config(text="☐ Deselect All" if self.all_selected else "☑ Select All")

    def stop_search(self):
        self.is_searching = False
        self.status_var.set("Stopping search... please wait.")
        self.cancel_btn.config(state=tk.DISABLED)

    def update_status(self, msg):
        self.status_var.set(msg)

    def safe_insert(self, item_id, check, name, address, city, state, country, rating, phone, email, website, fb, ig, li, tags):
        self.tree.insert('', 'end', iid=item_id, values=(check, name, address, city, state, country, rating, phone, email, website, fb, ig, li), tags=tags)
        count = len(self.tree.get_children())
        val_saved = count * 0.80
        self.roi_badge_var.set(f"💰 {count} Leads Extracted • ${val_saved:,.2f} Value Generated (Apollo/SaaS: ${val_saved:,.2f} | You: $0.00)")

    def start_search_thread(self):
        base_query = self.query_entry.get().strip()
        if not base_query:
            messagebox.showwarning("Error", "Please enter a search query.")
            return
            
        country = self.filter_country.get().strip()
        state = self.filter_state.get().strip()
        city = self.filter_city.get().strip()
        
        # Smart location appending: do not duplicate if user already typed it in the search query
        norm_base = normalize_text(base_query)
        loc_parts = []
        if city and normalize_text(city) not in norm_base:
            loc_parts.append(city)
        if state and state != "Any" and normalize_text(state) not in norm_base:
            loc_parts.append(state)
        if country and country != "Any" and normalize_text(country) not in norm_base:
            loc_parts.append(country)
            
        search_query = base_query
        if loc_parts:
            if re.search(r'\bin\b', base_query, re.IGNORECASE):
                search_query += ", " + ", ".join(loc_parts)
            else:
                search_query += " in " + ", ".join(loc_parts)
            
        self.roi_badge_var.set("💰 Searching... Live ROI: $0.00 (Apollo Cost: $0.00 | You: $0.00)")
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        self.is_searching = True
        self.search_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        
        threading.Thread(target=self.run_search_and_scrape, args=(search_query, country, state, city), daemon=True).start()

    def run_search_and_scrape(self, query, target_country, target_state, target_city):
        api_key = ""
        if hasattr(self.app, 'api_key_entry'):
            api_key = self.app.api_key_entry.get().strip()
        if not api_key:
            api_key = self.app.settings.get("api_key", "").strip()

        if not api_key:
            self.is_searching = False
            self.app.root.after(0, self.search_btn.config, {"state": tk.NORMAL})
            self.app.root.after(0, self.cancel_btn.config, {"state": tk.DISABLED})
            self.app.root.after(0, self.update_status, "Google Places API Key is missing. Please add it in Tab 4 (Settings).")
            def _ask_key():
                if messagebox.askyesno("Google Places Key Missing", "You need a Google Places API Key to extract leads from Google Maps.\n\nGoogle provides $200 free credit monthly (~10,000+ searches free).\n\nWould you like to open Google Cloud Console and configure your API key now?"):
                    webbrowser.open("https://console.cloud.google.com/google/maps-apis/credentials")
                    self.app.notebook.select(self.app.tab_settings)
            self.app.root.after(0, _ask_key)
            return

        self.app.settings["api_key"] = api_key
        self.app.auto_sync_settings()

        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.rating,places.websiteUri,places.nationalPhoneNumber,places.addressComponents,places.formattedAddress,nextPageToken"
        }
        
        try: min_r = float(self.filter_min_r.get())
        except: min_r = 0.0
        try: max_r = float(self.filter_max_r.get())
        except: max_r = 5.0
        
        req_w = self.filter_website.get()
        req_e = self.filter_email.get()
        req_s = self.filter_socials.get()
        
        passed_filters = 0
        page_token = ""
        page_count = 1
        
        while self.is_searching:
            self.app.root.after(0, self.update_status, f"Fetching Page {page_count} from Google Maps...")
            
            payload = {"textQuery": query}
            if page_token:
                payload["pageToken"] = page_token
                
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=15)
                response_data = response.json()
            except Exception as e:
                self.app.root.after(0, self.update_status, f"Connection Error: {e}")
                break

            if 'error' in response_data:
                err_msg = response_data['error'].get('message', 'Unknown')
                self.app.root.after(0, self.update_status, f"API Error: {err_msg}")
                self.app.root.after(0, messagebox.showerror, "Google API Error", f"The Google Places API returned an error:\n\n{err_msg}\n\nPlease check your API key and billing quota.")
                self.is_searching = False
                break
                
            places = response_data.get('places', [])
            
            for i, place in enumerate(places):
                if not self.is_searching: break
                    
                name = place.get('displayName', {}).get('text', 'Unknown')
                address = place.get('formattedAddress', '')
                rating = place.get('rating', 0.0)
                phone = place.get('nationalPhoneNumber', '')
                website = place.get('websiteUri', '')
                
                c_name = ""
                c_short = ""
                s_name = ""
                s_short = ""
                city_name = ""
                for component in place.get('addressComponents', []):
                    types = component.get('types', [])
                    if 'country' in types:
                        c_name = component.get('longText', '')
                        c_short = component.get('shortText', '')
                    if 'administrative_area_level_1' in types:
                        s_name = component.get('longText', '')
                        s_short = component.get('shortText', '')
                    if 'locality' in types or 'administrative_area_level_2' in types or 'postal_town' in types or 'sublocality' in types:
                        if not city_name:
                            city_name = component.get('longText', '')
                        
                all_address_parts = address + " " + " ".join([c.get('longText', '') for c in place.get('addressComponents', [])])
                
                # Robust international matching
                if not match_country(c_name, c_short, target_country):
                    continue
                if not match_state(s_name, s_short, address, target_state):
                    continue
                if not match_city(all_address_parts, target_city):
                    continue
                
                if not (min_r <= rating <= max_r):
                    continue
                    
                if req_w == "Required" and not website:
                    continue
                if req_w == "Missing" and website:
                    continue
                
                self.app.root.after(0, self.update_status, f"Analyzing: {name} (Page {page_count})")
                
                email = ""
                fb_url = ""
                ig_url = ""
                li_url = ""
                
                if website:
                    edata = self.enrich_website_fast(website)
                    email = edata['email']
                    fb_url = edata['fb']
                    ig_url = edata['ig']
                    li_url = edata['li']
                    
                has_socials = bool(fb_url or ig_url or li_url)
                
                if req_e == "Required" and not email:
                    continue
                if req_e == "Missing" and email:
                    continue
                if req_s == "Required" and not has_socials:
                    continue
                if req_s == "Missing" and has_socials:
                    continue
                
                passed_filters += 1
                
                already_emailed = False
                if self.is_prospector:
                    if email and email in self.app.history: already_emailed = True
                    if name in self.app.history: already_emailed = True
                
                check = '☐' if already_emailed else '☑'
                tags = ('emailed',) if already_emailed else ()
                item_id = f"row_{page_count}_{i}"
                
                self.app.root.after(0, lambda id=item_id, c=check, n=name, a=address, ci=city_name, st=s_name, cnt=c_name, r=rating, p=phone, e=email, w=website, fb=fb_url, ig=ig_url, li=li_url, t=tags: self.safe_insert(id, c, n, a, ci, st, cnt, r, p, e, w, fb, ig, li, t))
            
            page_token = response_data.get('nextPageToken', '')
            if not page_token:
                break
            
            page_count += 1
            time.sleep(2)
                    
        if self.is_searching:
            val_saved = passed_filters * 0.80
            final_roi = f"🎉 {passed_filters} Leads Captured • 💰 ${val_saved:,.2f} Value Saved (Apollo/SaaS: ${val_saved:,.2f} | Your Cost: $0.00)"
            self.app.root.after(0, self.roi_badge_var.set, final_roi)
            self.app.root.after(0, self.update_status, f"🎉 Search Complete! Extracted {passed_filters} businesses passing exact filters. Saved ${val_saved:,.2f}!")
            self.app.root.after(0, self.flash_completion)
            play_completion_chime("Glass")
            
        self.is_searching = False
        self.app.root.after(0, self.search_btn.config, {"state": tk.NORMAL})
        self.app.root.after(0, self.cancel_btn.config, {"state": tk.DISABLED})

    def enrich_website_fast(self, url):
        res = {'email': '', 'fb': '', 'ig': '', 'li': ''}
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(url, headers=headers, timeout=3)
            text = response.text
            
            # Check mailto: links first (highest quality)
            mailto_emails = re.findall(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', text, re.IGNORECASE)
            emails = mailto_emails + re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
            invalid = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.js', '.css', 'sentry.io', 'wixpress.com')
            valid_emails = [e for e in emails if not e.lower().endswith(invalid)]
            if valid_emails:
                res['email'] = max(set(valid_emails), key=valid_emails.count)
                
            fb = re.search(r'href=[\'"](https?://(?:www\.)?facebook\.com/[^\'"]+)[\'"]', text)
            ig = re.search(r'href=[\'"](https?://(?:www\.)?instagram\.com/[^\'"]+)[\'"]', text)
            li = re.search(r'href=[\'"](https?://(?:www\.)?linkedin\.com/[^\'"]+)[\'"]', text)
            
            if fb: res['fb'] = fb.group(1)
            if ig: res['ig'] = ig.group(1)
            if li: res['li'] = li.group(1)
            
        except:
            pass
        return res

    def get_selected_leads(self):
        selected = []
        for item in self.tree.get_children():
            values = self.tree.item(item, 'values')
            if values[0] == '☑':
                selected.append({
                    "id": item,
                    "name": values[1],
                    "address": values[2],
                    "city": values[3],
                    "state": values[4],
                    "country": values[5],
                    "rating": values[6],
                    "phone": values[7],
                    "email": values[8],
                    "website": values[9],
                    "facebook": values[10],
                    "instagram": values[11],
                    "linkedin": values[12]
                })
        return selected

    def export_selected(self):
        leads = self.get_selected_leads()
        if not leads:
            messagebox.showwarning("Warning", "No leads selected to export.")
            return
            
        default_name = f"Data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=default_name,
            title="Save CSV File As...",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        
        if not filepath:
            return # User cancelled
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["name", "address", "city", "state", "country", "rating", "phone", "email", "website", "facebook", "instagram", "linkedin"], extrasaction="ignore")
            writer.writeheader()
            for L in leads:
                writer.writerow(L)
            
        val_saved = len(leads) * 0.80
        play_completion_chime("Ping")
        self.update_status(f"Export successful: {len(leads)} records saved (SaaS Value: ${val_saved:,.2f}).")
        messagebox.showinfo("Export Successful 🎉", f"Data successfully saved to:\n{filepath}\n\n📊 {len(leads)} verified leads exported.\n💰 Estimated Apollo/SaaS Value: ${val_saved:,.2f} (Your Cost: $0.00)!")

    def send_to_mailer(self):
        leads = self.get_selected_leads()
        if not leads:
            for item in self.tree.get_children():
                v = self.tree.item(item, 'values')
                leads.append({
                    "id": item, "name": v[1], "address": v[2], "city": v[3],
                    "state": v[4], "country": v[5], "rating": v[6], "phone": v[7],
                    "email": v[8], "website": v[9]
                })
        if not leads:
            messagebox.showwarning("No Leads", "No leads to send. Run a search first.")
            return
        self.app.mailer_ui.load_external_leads(leads)
        self.app.notebook.select(self.app.tab_mailer)
        messagebox.showinfo("Leads Sent", f"Successfully loaded {len(leads)} leads into Tab 3 (Send AI Emails)!")

    def start_email_thread(self):
        if not self.is_prospector: return
        
        leads = self.get_selected_leads()
        valid_leads = [L for L in leads if L['email'].strip()]
        
        if not valid_leads:
            messagebox.showwarning("Warning", "None of the selected businesses have valid email addresses.")
            return
            
        email = self.app.settings.get("email", "")
        password = self.app.settings.get("password", "")
        if not email or not password:
            messagebox.showerror("Error", "Please enter your Gmail Address and App Password in the Settings tab.")
            return
            
        if messagebox.askyesno("Confirm", f"Ready to email pitch to {len(valid_leads)} businesses?"):
            self.email_btn.config(state=tk.DISABLED)
            threading.Thread(target=self.run_email_blast, args=(valid_leads, email, password), daemon=True).start()

    def run_email_blast(self, leads, my_email, my_password):
        sent_count = 0
        total = len(leads)
        
        t_name = self.app.settings.get("active_template", "")
        template = self.app.settings["templates"].get(t_name, {"subject":"", "body":""})
        subject_template = template["subject"]
        body_template = template["body"]
        use_ai = self.app.settings.get("use_ai", False)
        groq_key = self.app.settings.get("groq_api_key", "")
        
        if use_ai and not groq_key:
            self.app.root.after(0, messagebox.showerror, "AI Error", "Please add your Groq API Key in the Settings tab to use AI Auto-Pitch.")
            self.app.root.after(0, self.email_btn.config, {"state": tk.NORMAL})
            return
            
        for i, b in enumerate(leads):
            safe_name = b['name']
            city = b.get('city', 'their city')
            rating = b.get('rating', 'great')
            
            subject = subject_template.replace("{name}", safe_name).replace("{city}", city)
            
            if use_ai:
                self.app.root.after(0, self.update_status, f"🤖 AI is writing pitch {i+1}/{total} for {safe_name}...")
                prompt = body_template.replace("{name}", safe_name).replace("{city}", city).replace("{rating}", str(rating))
                
                # Call Groq LLM with active models and automatic fallback
                headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json"
                }
                models_to_try = get_groq_active_models(groq_key)
                body = prompt
                for model_id in models_to_try:
                    payload = {
                        "model": model_id,
                        "messages": [
                            {"role": "system", "content": "You are an elite B2B sales copywriter. Output ONLY the raw email body text. Do not include subject lines, markdown formatting, or introductory greetings like 'Here is the email'."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7
                    }
                    try:
                        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15)
                        if response.status_code == 200:
                            body = response.json()['choices'][0]['message']['content'].strip()
                            break
                    except Exception:
                        continue
            else:
                self.app.root.after(0, self.update_status, f"Sending pitch {i+1}/{total} to {safe_name}...")
                body = body_template.replace("{name}", safe_name)
            
            success = self.send_email(b['email'], subject, body, my_email, my_password)
            
            if success:
                if b['email']: self.app.history[b['email']] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.app.history[b['name']] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.app.save_history()
                
                self.app.root.after(0, self.tree.item, b['id'], {'tags': ('success',)})
                self.app.root.after(0, self.tree.set, b['id'], 'Select', '☐')
                sent_count += 1
                time.sleep(2)
            else:
                self.app.root.after(0, self.tree.item, b['id'], {'tags': ('fail',)})
                
        val_outreach = sent_count * 0.50
        play_completion_chime("Glass")
        self.app.root.after(0, self.flash_completion)
        self.app.root.after(0, self.update_status, f"🎉 Email sequence complete! {sent_count} sent • 💰 Saved ${val_outreach:,.2f} in SaaS outreach fees!")
        self.app.root.after(0, self.email_btn.config, {"state": tk.NORMAL})
        self.app.root.after(0, messagebox.showinfo, "Campaign Complete 🎉", f"Email sequence completed!\n\n✅ {sent_count} outreach pitches sent.\n💰 Estimated Outreach Value: ${val_outreach:,.2f} (Your Cost: $0.00)!")

    def send_email(self, target_email, subject, body, my_email, my_password):
        msg = MIMEMultipart()
        msg['From'] = my_email
        msg['To'] = target_email
        msg['Subject'] = Header(subject, 'utf-8')
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(my_email, my_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception:
            return False


class MailerTab:
    def __init__(self, parent_app, parent_frame):
        self.app = parent_app
        self.frame = parent_frame
        self.leads = []
        self.is_sending = False
        self.all_selected = True
        
        self.setup_ui()

    def setup_ui(self):
        main_container = ttk.Frame(self.frame)
        main_container.pack(expand=True, fill='both', padx=15, pady=15)
        
        # ---------------- LEFT COLUMN: CUSTOMERS / LEADS ----------------
        left_col = ttk.LabelFrame(main_container, text=" 1. Customer Leads (Upload or Pull) ", padding=10)
        left_col.pack(side='left', fill='both', expand=True, padx=(0, 10))
        
        top_lead_btns = ttk.Frame(left_col)
        top_lead_btns.pack(fill='x', pady=(0, 10))
        
        ttk.Button(top_lead_btns, text="📂 Upload Excel / CSV", command=self.import_leads_file, style="Accent.TButton").pack(side='left', padx=(0, 5))
        ttk.Button(top_lead_btns, text="🔄 Pull from Harvester", command=self.pull_from_harvester).pack(side='left', padx=5)
        ttk.Button(top_lead_btns, text="🗑 Clear", command=self.clear_leads).pack(side='right', padx=5)
        
        tree_frame = ttk.Frame(left_col)
        tree_frame.pack(fill='both', expand=True)
        
        scroll_y = ttk.Scrollbar(tree_frame, orient="vertical")
        scroll_y.pack(side='right', fill='y')
        
        cols = ('Select', 'Name', 'Email', 'City', 'Status')
        self.tree = ttk.Treeview(tree_frame, columns=cols, show='headings', selectmode='browse', yscrollcommand=scroll_y.set)
        scroll_y.config(command=self.tree.yview)
        
        self.tree.heading('Select', text='[X]')
        self.tree.heading('Name', text='Customer / Business')
        self.tree.heading('Email', text='Email Address')
        self.tree.heading('City', text='City')
        self.tree.heading('Status', text='Status')
        
        self.tree.column('Select', width=45, anchor='center', stretch=False)
        self.tree.column('Name', width=160, minwidth=120)
        self.tree.column('Email', width=180, minwidth=140)
        self.tree.column('City', width=100, minwidth=80)
        self.tree.column('Status', width=90, anchor='center', minwidth=80)
        
        self.tree.tag_configure('success', background='#2e7d32', foreground='white')
        self.tree.tag_configure('fail', background='#c62828', foreground='white')
        
        # Left Column Bottom Action Bar: Always anchored at bottom and 100% visible
        left_action_frame = ttk.LabelFrame(left_col, text=" 🚀 Outreach Actions (Selected Leads) ", padding=8)
        left_action_frame.pack(side='bottom', fill='x', pady=(8, 0))
        
        left_btn_row = ttk.Frame(left_action_frame)
        left_btn_row.pack(fill='x')
        
        self.left_bulk_btn = ttk.Button(left_btn_row, text="🚀 Send Bulk to Checked", command=self.send_bulk_customers, style="Accent.TButton")
        self.left_bulk_btn.pack(side='left', fill='x', expand=True, padx=(0, 4))
        
        self.left_single_btn = ttk.Button(left_btn_row, text="✉️ Send 1 to Selected", command=self.send_single_customer)
        self.left_single_btn.pack(side='left', fill='x', expand=True, padx=4)
        
        self.left_stop_btn = ttk.Button(left_btn_row, text="🛑 Stop", command=self.stop_sending, state=tk.DISABLED, style="Danger.TButton")
        self.left_stop_btn.pack(side='left', padx=(4, 0))

        lead_footer = ttk.Frame(left_col)
        lead_footer.pack(side='bottom', fill='x', pady=(6, 4))
        
        self.select_all_btn = ttk.Button(lead_footer, text="☑ Select All", command=self.toggle_all)
        self.select_all_btn.pack(side='left', padx=(0, 4))
        
        ttk.Button(lead_footer, text="☐ Deselect All", command=self.deselect_all).pack(side='left')
        
        self.leads_count_var = tk.StringVar(value="No leads loaded yet.")
        self.leads_count_lbl = ttk.Label(lead_footer, textvariable=self.leads_count_var, font=("Segoe UI", 10, "bold"), foreground="#2e7d32")
        self.leads_count_lbl.pack(side='right')

        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<ButtonRelease-1>', self.on_tree_click)
        self.tree.bind('<<TreeviewSelect>>', self.on_lead_selected)
        self.tree.bind('<Button-2>', self.show_tree_context_menu)
        self.tree.bind('<Button-3>', self.show_tree_context_menu)
        
        # ---------------- RIGHT COLUMN: AI EMAIL CREATOR & OUTREACH ----------------
        right_col = ttk.LabelFrame(main_container, text=" 2. AI Email Generator & Outreach ", padding=10)
        right_col.pack(side='right', fill='both', expand=True, padx=(10, 0))
        
        # Bottom Outreach Deck (Packed FIRST with side='bottom' so it is ALWAYS pinned and 100% visible)
        send_frame = ttk.LabelFrame(right_col, text=" 🚀 Outreach Dispatch Deck ", padding=10)
        send_frame.pack(side='bottom', fill='x', pady=(8, 0))
        
        send_btn_row = ttk.Frame(send_frame)
        send_btn_row.pack(fill='x', pady=(0, 4))
        
        self.bulk_send_btn = ttk.Button(send_btn_row, text="🚀 Send Bulk Emails (All Checked)", command=self.send_bulk_customers, style="Accent.TButton")
        self.bulk_send_btn.pack(side='left', padx=(0, 8))
        
        self.single_send_btn = ttk.Button(send_btn_row, text="✉️ Send to 1 Selected Lead", command=self.send_single_customer)
        self.single_send_btn.pack(side='left', padx=(0, 8))
        
        self.stop_send_btn = ttk.Button(send_btn_row, text="🛑 Stop", command=self.stop_sending, state=tk.DISABLED, style="Danger.TButton")
        self.stop_send_btn.pack(side='left')
        
        status_row = ttk.Frame(send_frame)
        status_row.pack(fill='x', pady=(4, 0))
        
        self.send_status_var = tk.StringVar(value="Ready to send.")
        self.send_status_lbl = ttk.Label(status_row, textvariable=self.send_status_var, font=("Segoe UI", 10, "bold"), foreground="#2e7d32")
        self.send_status_lbl.pack(side='left')

        # Template Manager Bar
        tpl_bar = ttk.Frame(right_col)
        tpl_bar.pack(side='top', fill='x', pady=(0, 8))
        
        ttk.Label(tpl_bar, text="Template:", font=("Segoe UI", 11, "bold")).pack(side='left', padx=(0, 5))
        self.template_names = list(self.app.settings.get("templates", {}).keys())
        self.template_combo = ttk.Combobox(tpl_bar, values=self.template_names, state='readonly', width=22, font=("Segoe UI", 10))
        self.template_combo.set(self.app.settings.get("active_template", self.template_names[0] if self.template_names else ""))
        self.template_combo.pack(side='left', padx=5)
        self.template_combo.bind("<<ComboboxSelected>>", self.on_template_change)
        
        ttk.Button(tpl_bar, text="+ New", command=self.new_template).pack(side='left', padx=3)
        ttk.Button(tpl_bar, text="💾 Save", command=self.save_template).pack(side='left', padx=3)
        ttk.Button(tpl_bar, text="🗑 Delete", command=self.delete_template).pack(side='left', padx=3)
        
        # Card A: AI Prompt Box
        prompt_card = ttk.LabelFrame(right_col, text=" ✨ AI Prompt (Tell the AI what to write) ", padding=8)
        prompt_card.pack(side='top', fill='x', pady=(0, 8))
        
        tag_bar = ttk.Frame(prompt_card)
        tag_bar.pack(fill='x', pady=(0, 4))
        ttk.Label(tag_bar, text="Insert into prompt:", font=("Segoe UI", 9, "italic")).pack(side='left', padx=(0, 4))
        ttk.Button(tag_bar, text="{name}", command=lambda: self.insert_var("{name}")).pack(side='left', padx=2)
        ttk.Button(tag_bar, text="{city}", command=lambda: self.insert_var("{city}")).pack(side='left', padx=2)
        ttk.Button(tag_bar, text="{rating}", command=lambda: self.insert_var("{rating}")).pack(side='left', padx=2)
        
        self.prompt_text = tk.Text(prompt_card, height=2, font=("Segoe UI", 11), wrap='word', relief='solid', borderwidth=1, padx=6, pady=6)
        self.prompt_text.pack(fill='x', pady=(0, 5))
        self.prompt_text.insert('1.0', "Write a short, engaging 3-sentence cold pitch to {name} in {city} offering high-converting local customer leads.")
        
        ai_action_row = ttk.Frame(prompt_card)
        ai_action_row.pack(fill='x')
        
        self.generate_btn = ttk.Button(ai_action_row, text="✨ Generate Draft with AI", command=self.generate_ai_draft, style="Accent.TButton")
        self.generate_btn.pack(side='left')
        
        self.ai_status_var = tk.StringVar(value="")
        ttk.Label(ai_action_row, textvariable=self.ai_status_var, font=("Segoe UI", 9, "bold")).pack(side='left', padx=10)
        
        # Card B: Editable Subject & Body
        editor_card = ttk.LabelFrame(right_col, text=" ✏️ Review & Edit Email (What customers will receive) ", padding=8)
        editor_card.pack(side='top', fill='both', expand=True)
        
        ttk.Label(editor_card, text="Email Subject:", font=("Segoe UI", 11, "bold")).pack(anchor='w', pady=(2, 2))
        self.subject_entry = ttk.Entry(editor_card, font=("Segoe UI", 11))
        self.subject_entry.pack(fill='x', pady=(0, 6))
        
        ttk.Label(editor_card, text="Email Body (Freely edit text below):", font=("Segoe UI", 11, "bold")).pack(anchor='w', pady=(2, 2))
        self.body_text = scrolledtext.ScrolledText(editor_card, height=7, font=("Segoe UI", 11), wrap='word', relief='solid', borderwidth=1, padx=6, pady=6)
        self.body_text.pack(fill='both', expand=True, pady=(0, 4))
        
        self.load_active_template()

    def flash_send_status(self):
        try:
            self.send_status_lbl.config(foreground="#00e676")
            def _revert():
                try:
                    self.send_status_lbl.config(foreground="#2e7d32")
                except Exception:
                    pass
            self.app.root.after(1800, _revert)
        except Exception:
            pass

    def on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region == "cell":
            column = self.tree.identify_column(event.x)
            if column == '#1':
                item = self.tree.identify_row(event.y)
                if item:
                    current = self.tree.set(item, 'Select')
                    new_val = '☐' if current == '☑' else '☑'
                    self.tree.set(item, 'Select', new_val)

    def on_lead_selected(self, event):
        item = self.tree.focus()
        if item:
            name = self.tree.set(item, 'Name')
            email = self.tree.set(item, 'Email')
            if email:
                self.send_status_var.set(f"Target: {name} ({email})")

    def toggle_all(self):
        self.all_selected = not self.all_selected
        val = '☑' if self.all_selected else '☐'
        for item in self.tree.get_children():
            self.tree.set(item, 'Select', val)
        self.select_all_btn.config(text="☐ Deselect All" if self.all_selected else "☑ Select All")

    def deselect_all(self):
        self.all_selected = False
        for item in self.tree.get_children():
            self.tree.set(item, 'Select', '☐')
        self.select_all_btn.config(text="☑ Select All")

    def toggle_single_lead(self, row_id):
        curr = self.tree.set(row_id, 'Select')
        self.tree.set(row_id, 'Select', '☐' if curr == '☑' else '☑')

    def show_tree_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            name = self.tree.set(row_id, 'Name')
            menu = tk.Menu(self.frame, tearoff=0)
            menu.add_command(label=f"✉️ Send Email to {name[:20]}", command=self.send_single_customer)
            menu.add_command(label="☑ Toggle Checked", command=lambda: self.toggle_single_lead(row_id))
            menu.add_separator()
            menu.add_command(label="🚀 Send Bulk to All Checked", command=self.send_bulk_customers)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

    def set_sending_ui_state(self, is_sending):
        send_state = tk.DISABLED if is_sending else tk.NORMAL
        stop_state = tk.NORMAL if is_sending else tk.DISABLED
        for btn in (getattr(self, 'bulk_send_btn', None), getattr(self, 'single_send_btn', None), 
                    getattr(self, 'left_bulk_btn', None), getattr(self, 'left_single_btn', None)):
            if btn: 
                try: btn.config(state=send_state)
                except Exception: pass
        for btn in (getattr(self, 'stop_send_btn', None), getattr(self, 'left_stop_btn', None)):
            if btn: 
                try: btn.config(state=stop_state)
                except Exception: pass

    def clear_leads(self):
        self.leads = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.leads_count_var.set("No leads loaded.")
        self.send_status_var.set("Ready to send.")

    def populate_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, L in enumerate(self.leads):
            iid = f"mlead_{i}"
            L['id'] = iid
            name = L.get('name', 'Unknown')
            email = L.get('email', '')
            city = L.get('city', '')
            status = "Ready" if email else "No Email"
            self.tree.insert('', 'end', iid=iid, values=('☑' if email else '☐', name, email, city, status))
        valid_cnt = sum(1 for L in self.leads if L.get('email'))
        val_saved = len(self.leads) * 0.80
        self.leads_count_var.set(f"📊 {len(self.leads)} Leads ({valid_cnt} emails) • 💰 ${val_saved:,.2f} SaaS Value (Free)")

    def load_external_leads(self, leads_list):
        self.leads = leads_list
        self.populate_tree()

    def pull_from_harvester(self):
        combined = []
        for item in self.app.prospector_ui.tree.get_children():
            v = self.app.prospector_ui.tree.item(item, 'values')
            combined.append({"name": v[1], "address": v[2], "city": v[3], "rating": v[6], "phone": v[7], "email": v[8]})
        if not combined:
            for item in self.app.harvester_ui.tree.get_children():
                v = self.app.harvester_ui.tree.item(item, 'values')
                combined.append({"name": v[1], "address": v[2], "city": v[3], "rating": v[6], "phone": v[7], "email": v[8]})
        if not combined:
            messagebox.showinfo("No Leads Found", "No leads found in Tab 1 or Tab 2. Search for leads first or upload a CSV/Excel file.")
            return
        self.load_external_leads(combined)
        messagebox.showinfo("Leads Loaded", f"Successfully loaded {len(combined)} leads from Harvester!")

    def import_leads_file(self):
        try:
            filepath = filedialog.askopenfilename(
                title="Select Customer Leads File",
                filetypes=[
                    ("All Supported Files", ("*.csv", "*.xlsx", "*.xls")),
                    ("Excel Spreadsheet", ("*.xlsx", "*.xls")),
                    ("CSV File", "*.csv"),
                    ("All Files", "*.*")
                ]
            )
        except Exception:
            try:
                filepath = filedialog.askopenfilename(title="Select Customer Leads File")
            except Exception:
                filepath = ""

        if not filepath:
            return
            
        try:
            parsed_leads = []
            if filepath.lower().endswith(('.xlsx', '.xls')):
                parsed_leads = self.parse_xlsx_file(filepath)
            else:
                parsed_leads = self.parse_csv_file(filepath)
                
            if not parsed_leads:
                messagebox.showwarning("No Contacts Found", "Could not find any customer records or email addresses in this file.")
                return
                
            self.load_external_leads(parsed_leads)
            valid_count = sum(1 for L in parsed_leads if L.get('email'))
            messagebox.showinfo("Leads Imported", f"Successfully imported {len(parsed_leads)} leads!\n{valid_count} have valid emails ready for outreach.")
        except Exception as ex:
            messagebox.showerror("Import Error", f"Could not read the selected file:\n\n{ex}")

    def parse_csv_file(self, filepath):
        leads = []
        for enc in ['utf-8-sig', 'utf-8', 'latin-1']:
            try:
                with open(filepath, 'r', encoding=enc, errors='replace') as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        email, name, city, rating, phone, address = '', '', '', '', '', ''
                        for k, v in r.items():
                            if not k: continue
                            kl = k.lower().strip()
                            vl = str(v).strip()
                            if any(w in kl for w in ['email', 'mail', 'e-mail']): email = vl
                            elif any(w in kl for w in ['name', 'business', 'company', 'title']): name = vl
                            elif any(w in kl for w in ['city', 'district', 'town', 'locality']): city = vl
                            elif any(w in kl for w in ['rating', 'stars', 'score']): rating = vl
                            elif any(w in kl for w in ['phone', 'mobile', 'tel', 'cell']): phone = vl
                            elif any(w in kl for w in ['address', 'location']): address = vl
                        if email or name:
                            leads.append({'name': name or 'Customer', 'email': email, 'city': city or '', 'rating': rating or '5.0', 'phone': phone, 'address': address})
                break
            except Exception:
                continue
        return leads

    def parse_xlsx_file(self, filepath):
        leads = []
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
            sheet = wb.active
            rows = []
            for r in sheet.iter_rows(values_only=True):
                if any(r):
                    rows.append([str(c).strip() if c is not None else '' for c in r])
        except Exception:
            rows = []
            try:
                import zipfile
                import xml.etree.ElementTree as ET
                with zipfile.ZipFile(filepath, 'r') as z:
                    shared = []
                    if 'xl/sharedStrings.xml' in z.namelist():
                        tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
                        for si in tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                            texts = [t.text for t in si.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t') if t.text]
                            shared.append(''.join(texts))
                    sheet_xml = z.read('xl/worksheets/sheet1.xml')
                    sheet_tree = ET.fromstring(sheet_xml)
                    for r in sheet_tree.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
                        row_data = []
                        for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                            v = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                            val = v.text if v is not None and v.text else ''
                            if c.get('t') == 's' and val.isdigit() and int(val) < len(shared):
                                val = shared[int(val)]
                            row_data.append(val.strip())
                        if any(row_data):
                            rows.append(row_data)
            except Exception:
                pass

        if len(rows) > 1:
            headers = [h.lower() for h in rows[0]]
            for row in rows[1:]:
                row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                email = next((v for k, v in row_dict.items() if any(w in k for w in ['email', 'mail'])), '')
                name = next((v for k, v in row_dict.items() if any(w in k for w in ['name', 'business', 'company'])), '')
                city = next((v for k, v in row_dict.items() if any(w in k for w in ['city', 'district', 'town'])), '')
                rating = next((v for k, v in row_dict.items() if any(w in k for w in ['rating', 'stars'])), '')
                phone = next((v for k, v in row_dict.items() if any(w in k for w in ['phone', 'mobile', 'tel'])), '')
                address = next((v for k, v in row_dict.items() if any(w in k for w in ['address', 'location'])), '')
                if email or name:
                    leads.append({'name': name or 'Customer', 'email': email, 'city': city or '', 'rating': rating or '5.0', 'phone': phone, 'address': address})
        return leads

    def insert_var(self, tag):
        self.prompt_text.insert(tk.INSERT, tag)

    def generate_ai_draft(self):
        prompt_instruction = self.prompt_text.get('1.0', tk.END).strip()
        if not prompt_instruction:
            messagebox.showwarning("Prompt Missing", "Please enter what you want the AI to write.")
            return
            
        # Check live UI entry in Settings as well as settings dict
        groq_key = ""
        if hasattr(self.app, 'groq_api_entry'):
            groq_key = self.app.groq_api_entry.get().strip()
        if not groq_key:
            groq_key = self.app.settings.get("groq_api_key", "").strip()
            
        if not groq_key:
            # Let the user paste the key directly right here OR open the portal!
            key_input = simpledialog.askstring(
                "Groq AI Key Needed", 
                "Enter or Paste your free Groq API Key:\n\n(If you don't have one, click Cancel to open console.groq.com/keys)"
            )
            if key_input and key_input.strip():
                groq_key = key_input.strip()
                self.app.settings["groq_api_key"] = groq_key
                if hasattr(self.app, 'groq_api_entry'):
                    self.app.groq_api_entry.delete(0, tk.END)
                    self.app.groq_api_entry.insert(0, groq_key)
                self.app.save_settings()
                messagebox.showinfo("Key Saved ✅", "Groq AI Key saved successfully! Generating your draft now...")
            else:
                if messagebox.askyesno("Open Free Groq Console", "Would you like to open https://console.groq.com/keys in your browser to copy your free API key?"):
                    webbrowser.open("https://console.groq.com/keys")
                    self.app.notebook.select(self.app.tab_settings)
                return
        else:
            # Sync key to settings and persist
            self.app.settings["groq_api_key"] = groq_key
            self.app.save_settings()
            
        selected_item = self.tree.focus()
        sample = {"name": "Apex Services", "city": "Austin", "rating": "4.9"}
        if selected_item:
            for L in self.leads:
                if L.get('id') == selected_item:
                    sample = L
                    break
        elif self.leads:
            sample = self.leads[0]
            
        user_prompt = prompt_instruction.replace("{name}", sample.get('name', 'Business')).replace("{city}", sample.get('city', 'your city')).replace("{rating}", str(sample.get('rating', '5.0')))
        
        self.ai_status_var.set("🤖 Generating with AI...")
        self.generate_btn.config(state=tk.DISABLED)
        
        def run_ai():
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            system_msg = "You are an elite B2B sales copywriter. Respond with JSON containing 'subject' and 'body'. The body should be professional, short (under 100 words), persuasive, and ready to send. Example format: {\"subject\": \"Quick question for {name}\", \"body\": \"Hi {name} team...\"}"
            models_to_try = get_groq_active_models(groq_key)
            generated_success = False
            last_err = ""
            for model_id in models_to_try:
                payload = {
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.7,
                    "response_format": {"type": "json_object"}
                }
                try:
                    resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15)
                    if resp.status_code == 200:
                        content = resp.json()['choices'][0]['message']['content'].strip()
                        # Clean potential markdown markdown blocks
                        clean_content = content
                        if "```json" in clean_content:
                            clean_content = clean_content.split("```json")[1].split("```")[0].strip()
                        elif "```" in clean_content:
                            clean_content = clean_content.split("```")[1].split("```")[0].strip()
                        try:
                            res_json = json.loads(clean_content)
                            subj = res_json.get("subject", f"Connecting regarding {sample.get('name')}")
                            body = res_json.get("body", clean_content)
                        except Exception:
                            match = re.search(r'\{.*"subject".*"body".*\}', clean_content, re.DOTALL)
                            if match:
                                try:
                                    res_json = json.loads(match.group(0))
                                    subj = res_json.get("subject", f"Connecting regarding {sample.get('name')}")
                                    body = res_json.get("body", clean_content)
                                except Exception:
                                    subj = f"Connecting regarding {sample.get('name')}"
                                    body = clean_content
                            else:
                                subj = f"Connecting regarding {sample.get('name')}"
                                body = clean_content
                        self.app.root.after(0, self.update_generated_draft, subj, body)
                        display_name = model_id.split('/')[-1] if '/' in model_id else model_id
                        self.app.root.after(0, lambda m=display_name: self.ai_status_var.set(f"✅ Draft Generated ({m})!"))
                        play_completion_chime("Ping")
                        generated_success = True
                        break
                    else:
                        last_err = resp.text
                        continue
                except Exception as ex:
                    last_err = str(ex)
                    continue

            self.app.root.after(0, lambda: self.generate_btn.config(state=tk.NORMAL))
            if not generated_success:
                self.app.root.after(0, lambda: messagebox.showerror("AI Error", f"Groq API returned an error:\n{last_err}"))
                self.app.root.after(0, lambda: self.ai_status_var.set("❌ Generation Failed"))
                
        threading.Thread(target=run_ai, daemon=True).start()

    def update_generated_draft(self, subject, body):
        self.subject_entry.delete(0, tk.END)
        self.subject_entry.insert(0, subject)
        self.body_text.delete('1.0', tk.END)
        self.body_text.insert('1.0', body)
        self.send_status_var.set("Draft updated! Review & edit above before sending.")

    def send_single_customer(self):
        selected_item = self.tree.focus()
        target_lead = None
        for L in self.leads:
            if L.get('id') == selected_item:
                target_lead = L
                break
                
        if not target_lead or not target_lead.get('email'):
            # Fallback: check if exactly 1 lead is selected or checked
            checked = [L for L in self.leads if self.tree.set(L['id'], 'Select') == '☑' and L.get('email', '').strip()]
            if len(checked) == 1:
                target_lead = checked[0]
            elif checked:
                target_lead = checked[0]

        if not target_lead or not target_lead.get('email'):
            messagebox.showwarning("Select Customer", "Please click on a customer with a valid email address in the left table first.")
            return
            
        my_email = self.app.settings.get("email", "").strip()
        my_password = self.app.settings.get("password", "").strip()
        if not my_email or not my_password:
            if messagebox.askyesno("Credentials Missing", "You need to configure your Gmail Address and 16-character App Password in Settings to send emails.\n\nWould you like to open Settings now?"):
                self.app.notebook.select(self.app.tab_settings)
            return
            
        subj_tmpl = self.subject_entry.get().strip()
        body_tmpl = self.body_text.get('1.0', tk.END).strip()
        if not subj_tmpl or not body_tmpl:
            messagebox.showwarning("Empty Email", "Subject or body cannot be empty.")
            return
            
        subj = subj_tmpl.replace("{name}", target_lead.get('name', '')).replace("{city}", target_lead.get('city', ''))
        body = body_tmpl.replace("{name}", target_lead.get('name', '')).replace("{city}", target_lead.get('city', '')).replace("{rating}", str(target_lead.get('rating', '')))
        
        if messagebox.askyesno("Confirm Send", f"Send this email now to {target_lead.get('name')} ({target_lead.get('email')})?"):
            self.send_status_var.set(f"Sending to {target_lead.get('name')}...")
            success = self.send_email_smtp(target_lead.get('email'), subj, body, my_email, my_password)
            if success:
                play_completion_chime("Ping")
                self.tree.item(target_lead['id'], tags=('success',))
                self.tree.set(target_lead['id'], 'Status', 'Sent ✅')
                self.send_status_var.set("Email Sent Successfully ✅ • 💰 $0.50 Outreach Value Saved")
                self.flash_send_status()
                messagebox.showinfo("Success", f"Email successfully delivered to {target_lead.get('email')}!")
            else:
                self.tree.item(target_lead['id'], tags=('fail',))
                self.tree.set(target_lead['id'], 'Status', 'Failed ❌')
                self.send_status_var.set("Send Failed ❌")
                messagebox.showerror("Failed", f"Could not send email to {target_lead.get('email')}. Please check your Gmail App password in Settings.")

    def stop_sending(self):
        self.is_sending = False
        self.set_sending_ui_state(False)
        self.send_status_var.set("Stopping bulk send...")

    def send_bulk_customers(self):
        checked_leads = [L for L in self.leads if self.tree.set(L['id'], 'Select') == '☑' and L.get('email', '').strip()]
        if not checked_leads:
            messagebox.showwarning("No Leads Selected", "Please select at least one customer with a valid email address.")
            return
            
        my_email = self.app.settings.get("email", "").strip()
        my_password = self.app.settings.get("password", "").strip()
        if not my_email or not my_password:
            if messagebox.askyesno("Credentials Missing", "You need to configure your Gmail Address and 16-character App Password in Settings to send emails.\n\nWould you like to open Settings now?"):
                self.app.notebook.select(self.app.tab_settings)
            return
            
        subj_tmpl = self.subject_entry.get().strip()
        body_tmpl = self.body_text.get('1.0', tk.END).strip()
        if not subj_tmpl or not body_tmpl:
            messagebox.showwarning("Empty Email", "Subject or body cannot be empty.")
            return
            
        if messagebox.askyesno("Confirm Bulk Send", f"Ready to send personalized emails to {len(checked_leads)} customer(s)?"):
            self.is_sending = True
            self.set_sending_ui_state(True)
            
            def run_bulk():
                sent_count = 0
                total = len(checked_leads)
                for idx, L in enumerate(checked_leads):
                    if not self.is_sending: break
                    self.app.root.after(0, self.send_status_var.set, f"Sending {idx+1}/{total} to {L.get('name')}...")
                    s = subj_tmpl.replace("{name}", L.get('name', '')).replace("{city}", L.get('city', ''))
                    b = body_tmpl.replace("{name}", L.get('name', '')).replace("{city}", L.get('city', '')).replace("{rating}", str(L.get('rating', '')))
                    ok = self.send_email_smtp(L.get('email'), s, b, my_email, my_password)
                    if ok:
                        sent_count += 1
                        self.app.root.after(0, self.tree.item, L['id'], {'tags': ('success',)})
                        self.app.root.after(0, self.tree.set, L['id'], 'Status', 'Sent ✅')
                    else:
                        self.app.root.after(0, self.tree.item, L['id'], {'tags': ('fail',)})
                        self.app.root.after(0, self.tree.set, L['id'], 'Status', 'Failed ❌')
                    time.sleep(1.5)
                    
                self.is_sending = False
                val_outreach = sent_count * 0.50
                play_completion_chime("Glass")
                msg_status = f"🎉 Bulk Blast Complete! {sent_count}/{total} Sent • 💰 Saved ${val_outreach:,.2f} in SaaS Fees!"
                self.app.root.after(0, lambda: self.set_sending_ui_state(False))
                self.app.root.after(0, self.send_status_var.set, msg_status)
                self.app.root.after(0, self.flash_send_status)
                self.app.root.after(0, lambda: messagebox.showinfo("Campaign Complete 🎉", f"Bulk email campaign finished!\n\n✅ {sent_count} of {total} emails successfully delivered.\n💰 Estimated SaaS Outreach Value: ${val_outreach:,.2f} (Your Cost: $0.00)!"))
                
            threading.Thread(target=run_bulk, daemon=True).start()

    def send_email_smtp(self, target_email, subject, body, my_email, my_password):
        msg = MIMEMultipart()
        msg['From'] = my_email
        msg['To'] = target_email
        msg['Subject'] = Header(subject, 'utf-8')
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(my_email, my_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception:
            return False

    def load_active_template(self):
        t_name = self.template_combo.get()
        if not t_name: return
        t = self.app.settings.get("templates", {}).get(t_name, {})
        self.subject_entry.delete(0, tk.END)
        self.subject_entry.insert(0, t.get("subject", ""))
        self.body_text.delete('1.0', tk.END)
        self.body_text.insert('1.0', t.get("body", ""))
        if "prompt" in t:
            self.prompt_text.delete('1.0', tk.END)
            self.prompt_text.insert('1.0', t.get("prompt", ""))

    def on_template_change(self, event):
        self.load_active_template()
        self.app.settings["active_template"] = self.template_combo.get()
        self.app.save_settings()

    def new_template(self):
        name = simpledialog.askstring("New Template", "Enter new template name:")
        if name:
            if "templates" not in self.app.settings:
                self.app.settings["templates"] = {}
            self.app.settings["templates"][name] = {"subject": "", "body": "", "prompt": ""}
            self.template_combo['values'] = list(self.app.settings["templates"].keys())
            self.template_combo.set(name)
            self.load_active_template()
            self.app.save_settings()

    def delete_template(self):
        name = self.template_combo.get()
        if len(self.app.settings.get("templates", {})) <= 1:
            messagebox.showwarning("Warning", "Cannot delete the last remaining template.")
            return
        if messagebox.askyesno("Delete", f"Delete template '{name}'?"):
            del self.app.settings["templates"][name]
            new_name = list(self.app.settings["templates"].keys())[0]
            self.template_combo['values'] = list(self.app.settings["templates"].keys())
            self.template_combo.set(new_name)
            self.load_active_template()
            self.app.save_settings()

    def save_template(self):
        name = self.template_combo.get()
        if not name:
            name = "Default Pitch"
        if "templates" not in self.app.settings:
            self.app.settings["templates"] = {}
        self.app.settings["templates"][name] = {
            "subject": self.subject_entry.get().strip(),
            "body": self.body_text.get('1.0', tk.END).strip(),
            "prompt": self.prompt_text.get('1.0', tk.END).strip()
        }
        self.app.settings["active_template"] = name
        self.app.save_settings()
        messagebox.showinfo("Saved", f"Template '{name}' saved successfully!")


class NexusHarvesterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Nexus Harvester")
        self.root.geometry("1400x850")
        
        # High-DPI scaling configuration for crisp rendering on Windows 10/11
        if os.name == 'nt':
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass

        # Configure modern ttk Theme & Styles matching macOS aesthetic
        self.style = ttk.Style(self.root)
        self.apply_modern_theme()
        
        try:
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base_dir, "icon_512x512.png")
            if os.path.exists(icon_path):
                img = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, img)
        except Exception:
            pass
        
        self.settings = self.load_settings()
        self.history = self.load_history()
        
        # Center notebook layout nicely
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(expand=True, fill='both', padx=20, pady=20)
        
        self.tab_harvester = ttk.Frame(self.notebook)
        self.tab_prospector = ttk.Frame(self.notebook)
        self.tab_mailer = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_harvester, text=' 1. Data Harvester ')
        self.notebook.add(self.tab_prospector, text=' 2. Buyer Prospector ')
        self.notebook.add(self.tab_mailer, text=' 3. Send AI Emails ')
        self.notebook.add(self.tab_settings, text=' 4. Settings ')
        
        self.setup_settings_tab()
        self.harvester_ui = ScraperTab(self, self.tab_harvester, is_prospector=False)
        self.prospector_ui = ScraperTab(self, self.tab_prospector, is_prospector=True)
        self.mailer_ui = MailerTab(self, self.tab_mailer)

        self.root.bind("<Button-1>", self.clear_focus)
        
    def clear_focus(self, event):
        # Only clear focus if clicking on a background frame, notebook, or root
        import tkinter as tk
        from tkinter import ttk
        if event.widget == self.root or isinstance(event.widget, (ttk.Frame, ttk.LabelFrame, ttk.Notebook, tk.Frame)):
            self.root.focus_set()

    def apply_modern_theme(self):
        if os.name == 'nt':
            if 'clam' in self.style.theme_names():
                self.style.theme_use('clam')

            BG_COLOR = "#f4f6f9"
            CARD_BG = "#ffffff"
            TEXT_MAIN = "#1e293b"
            TEXT_MUTED = "#64748b"
            PRIMARY = "#0066cc"
            PRIMARY_HOVER = "#0052a3"
            BORDER = "#d1d5db"
            ROW_SELECT = "#2563eb"
            HEADER_BG = "#f1f5f9"

            self.root.configure(bg=BG_COLOR)

            self.style.configure(".", background=BG_COLOR, foreground=TEXT_MAIN, font=("Segoe UI", 10))
            self.style.configure("TFrame", background=BG_COLOR)
            self.style.configure("TLabelframe", background=CARD_BG, bordercolor=BORDER, relief="solid", borderwidth=1)
            self.style.configure("TLabelframe.Label", background=CARD_BG, foreground=TEXT_MAIN, font=("Segoe UI", 10, "bold"))

            # Modern flat tabs
            self.style.configure("TNotebook", background=BG_COLOR, tabmargins=[4, 4, 4, 0], borderwidth=0)
            self.style.configure("TNotebook.Tab", background="#e2e8f0", foreground=TEXT_MUTED, padding=[18, 9], font=("Segoe UI", 10, "bold"), borderwidth=0)
            self.style.map("TNotebook.Tab",
                background=[("selected", CARD_BG), ("active", "#cbd5e1")],
                foreground=[("selected", PRIMARY), ("active", TEXT_MAIN)]
            )

            # Modern Standard Buttons
            self.style.configure("TButton",
                background="#ffffff",
                foreground=TEXT_MAIN,
                font=("Segoe UI", 10),
                padding=[12, 6],
                relief="solid",
                borderwidth=1,
                bordercolor=BORDER
            )
            self.style.map("TButton",
                background=[("active", "#f1f5f9"), ("pressed", "#e2e8f0"), ("disabled", "#f8fafc")],
                foreground=[("disabled", "#94a3b8")]
            )

            # Accent Buttons (Blue)
            self.style.configure("Accent.TButton",
                background=PRIMARY,
                foreground="#ffffff",
                font=("Segoe UI", 10, "bold"),
                padding=[14, 7],
                relief="flat",
                borderwidth=0
            )
            self.style.map("Accent.TButton",
                background=[("active", PRIMARY_HOVER), ("pressed", "#003d7a"), ("disabled", "#94a3b8")],
                foreground=[("disabled", "#ffffff")]
            )

            # Danger Buttons (Red)
            self.style.configure("Danger.TButton",
                background="#dc2626",
                foreground="#ffffff",
                font=("Segoe UI", 10, "bold"),
                padding=[12, 6],
                relief="flat",
                borderwidth=0
            )
            self.style.map("Danger.TButton",
                background=[("active", "#b91c1c"), ("pressed", "#991b1b")]
            )

            # Treeview (Modern Lead Table)
            self.style.configure("Treeview",
                background=CARD_BG,
                fieldbackground=CARD_BG,
                foreground=TEXT_MAIN,
                rowheight=28,
                font=("Segoe UI", 10),
                borderwidth=1,
                relief="solid",
                bordercolor=BORDER
            )
            self.style.configure("Treeview.Heading",
                background=HEADER_BG,
                foreground=TEXT_MAIN,
                font=("Segoe UI", 10, "bold"),
                padding=[6, 7],
                relief="flat",
                borderwidth=1
            )
            self.style.map("Treeview",
                background=[("selected", ROW_SELECT)],
                foreground=[("selected", "#ffffff")]
            )
            self.style.map("Treeview.Heading",
                background=[("active", "#e2e8f0")]
            )

            self.style.configure("TEntry", fieldbackground=CARD_BG, foreground=TEXT_MAIN, padding=5)
            self.style.configure("TCombobox", fieldbackground=CARD_BG, foreground=TEXT_MAIN, padding=5)
            self.style.configure("TSpinbox", fieldbackground=CARD_BG, foreground=TEXT_MAIN, padding=5)
            self.style.configure("Horizontal.TProgressbar", background=PRIMARY, troughcolor="#e2e8f0", borderwidth=0)
        else:
            # macOS Native Theme (aqua)
            if 'aqua' in self.style.theme_names():
                self.style.theme_use('aqua')
            self.style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
            self.style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
            self.style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
            self.style.configure("TNotebook.Tab", padding=(16, 8), font=("Segoe UI", 10, "bold"))
            
    def load_settings(self):
        agency_templates = {
            "Website Redesign & Speed": {
                "subject": "Quick design observation regarding {name}",
                "prompt": "Write an engaging cold email to {name} in {city} pointing out how modernizing their website and mobile loading speed can capture twice as many paying customers.",
                "body": "Hi {name} team,\n\nI was researching top businesses in {city} and came across {name}. You have fantastic customer reviews, but I noticed your website is missing modern mobile optimization and clear call-to-action buttons.\n\nOver 65% of local searches happen on mobile devices, and having a slow or outdated layout is likely costing you high-intent local inquiries every week.\n\nWe recently redesigned a similar business's site and boosted their qualified quote requests by 42% in 30 days.\n\nWould you be open to a free 2-minute video mockup showing what a modern, high-converting site would look like for {name}?\n\nBest regards,\nModern Web Studio"
            },
            "Google Maps & Local SEO": {
                "subject": "Google Maps ranking & local visibility for {name}",
                "prompt": "Write a short cold email to {name} in {city} offering a free 1-page local SEO audit to rank them in the Google 3-Pack and outrank local competitors.",
                "body": "Hi {name} team,\n\nI was searching for services in {city} and saw that {name} has a strong reputation (rating: {rating}★), but your profile isn't ranking in the Google Maps top 3-pack where 75% of customer phone calls go.\n\nCompetitors with fewer positive reviews are capturing the majority of search traffic simply due to a few missing local keyword citations.\n\nWe specialize in Google Business Profile optimization to help businesses in {city} dominate local search.\n\nCan I send you a free 1-page local ranking audit showing the 3 quick fixes to move {name} into the top 3 spots this month?\n\nBest regards,\nLocal SEO Specialist"
            },
            "AI Chatbot & Automation": {
                "subject": "Never miss another customer lead at {name}",
                "prompt": "Write a concise pitch to {name} in {city} showing how an AI receptionist responds in under 15 seconds to website inquiries and books appointments automatically.",
                "body": "Hi {name} team,\n\nDid you know that 78% of local clients hire the first business that responds to their inquiry? After-hours inquiries usually bounce directly to competitors.\n\nWe install custom 24/7 AI Receptionists for businesses in {city}. The AI answers customer questions, gives pricing ranges, and books qualified appointments on your calendar 24/7 in under 15 seconds.\n\nWould you be open to a 60-second interactive demo link so you can test it live on your phone and see how it works for {name}?\n\nBest regards,\nAI Automation Team"
            },
            "Social Media & Reels Growth": {
                "subject": "Viral reels & local customer reach for {name}",
                "prompt": "Write a compelling cold pitch to {name} in {city} offering done-for-you short-form video reels (Instagram/TikTok/YouTube) to drive local foot traffic and sales.",
                "body": "Hi {name} team,\n\nI've been following your work at {name} in {city}! You have a great service, but your brand is leaving thousands of local views on the table by not publishing weekly short-form video reels.\n\nShort-form video is currently the #1 organic channel for getting local attention without spending money on expensive paid ads.\n\nWe produce done-for-you reels that turn local viewers into paying clients.\n\nCan I send you 3 free viral video concepts crafted specifically for {name} to review? No pressure either way.\n\nBest regards,\nSocial Content Agency"
            },
            "Data Arbitrage (Sell Lead Lists)": {
                "subject": "Connecting regarding verified client leads in {city}",
                "prompt": "Write a high-converting cold email to {name} in {city} offering a freshly compiled list of local verified client leads ready for immediate sales outreach.",
                "body": "Hi {name} team,\n\nI just finished compiling a fully verified list of local businesses in your industry across {city}, complete with direct owner emails, phone numbers, and websites.\n\nSince you provide high-ticket services to these types of clients, I wanted to see if your sales team would be interested in acquiring this verified lead list for outbound sales.\n\nWe offer the complete clean dataset for a flat $150. If you'd like to inspect it first, simply reply to this email and I'll send over 5 free sample contacts right away.\n\nBest regards,\nLead Growth Team"
            }
        }
        default = {
            "api_key": "",
            "groq_api_key": "",
            "use_ai": False,
            "email": "", 
            "password": "",
            "templates": agency_templates,
            "active_template": "Website Redesign & Speed"
        }
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    user_templates = loaded.get("templates", {})
                    merged_templates = dict(agency_templates)
                    merged_templates.update(user_templates)
                    default.update(loaded)
                    default["templates"] = merged_templates
            except:
                pass

        # Purge hardcoded/developer test keys from disk and memory
        DEVELOPER_KEYS_BLACKLIST = {
            "AIzaSyCWnXaGL7ZGhBUzQHR43f4ybpXGbWZbric",
        }
        if default.get("api_key") in DEVELOPER_KEYS_BLACKLIST or "AIzaSyCWnXaGL7ZGhBUzQHR43f4ybpXGbWZbric" in str(default.get("api_key", "")):
            default["api_key"] = ""
            try:
                if os.path.exists(SETTINGS_FILE):
                    with open(SETTINGS_FILE, 'w') as f:
                        json.dump(default, f, indent=4)
            except Exception:
                pass

        return default

    def open_url(self, url):
        webbrowser.open(url)

    def auto_sync_settings(self):
        try:
            DEVELOPER_KEYS_BLACKLIST = {
                "AIzaSyCWnXaGL7ZGhBUzQHR43f4ybpXGbWZbric",
            }
            if hasattr(self, 'api_key_entry'):
                val = self.api_key_entry.get().strip()
                if val in DEVELOPER_KEYS_BLACKLIST or "AIzaSyCWnXaGL7ZGhBUzQHR43f4ybpXGbWZbric" in val:
                    val = ""
                self.settings["api_key"] = val
            if hasattr(self, 'email_entry'):
                self.settings["email"] = self.email_entry.get().strip()
            if hasattr(self, 'password_entry'):
                self.settings["password"] = self.password_entry.get().strip()
            if hasattr(self, 'groq_api_entry'):
                self.settings["groq_api_key"] = self.groq_api_entry.get().strip()
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except Exception:
            pass

    def paste_to_entry(self, entry_widget):
        try:
            val = self.root.clipboard_get().strip()
            if val:
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, val)
                self.auto_sync_settings()
        except Exception:
            pass

    def toggle_password_visibility(self):
        if self.password_entry.cget('show') == '':
            self.password_entry.config(show='•')
            self.show_pwd_btn.config(text="👁️ Show")
        else:
            self.password_entry.config(show='')
            self.show_pwd_btn.config(text="🙈 Hide")

    def test_google_places_key(self):
        key = self.api_key_entry.get().strip()
        if not key:
            messagebox.showwarning("Key Missing", "Please enter or paste your Google Places API Key first.")
            return
        self.settings["api_key"] = key
        self.auto_sync_settings()
        self.google_status_lbl.config(text="🔄 Testing connection...", foreground="#f57c00")
        def _test():
            try:
                headers = {
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": key,
                    "X-Goog-FieldMask": "places.displayName"
                }
                payload = {"textQuery": "restaurant", "pageSize": 1}
                resp = requests.post("https://places.googleapis.com/v1/places:searchText", headers=headers, json=payload, timeout=8)
                if resp.status_code == 200:
                    self.root.after(0, lambda: self.google_status_lbl.config(text="✅ Places API Verified & Active!", foreground="#00c853"))
                    play_completion_chime("Ping")
                    self.root.after(0, lambda: messagebox.showinfo("Google Places Key Valid", "Success! Your Google Places API Key is valid and active.\n\nGoogle Maps lead extraction is ready to use!"))
                elif resp.status_code == 403:
                    self.root.after(0, lambda: self.google_status_lbl.config(text="❌ 403: Places API (New) Not Enabled", foreground="#d50000"))
                    self.root.after(0, lambda: messagebox.showerror("Google Places Error", "API Key exists, but 'Places API (New)' is not enabled in your Google Cloud Console project.\n\nPlease enable 'Places API (New)' under APIs & Services in Google Cloud Console."))
                elif resp.status_code == 400:
                    self.root.after(0, lambda: self.google_status_lbl.config(text="❌ Invalid API Key (400)", foreground="#d50000"))
                    self.root.after(0, lambda: messagebox.showerror("Invalid Key", "Google Cloud reported this API key is invalid or expired. Please check your credentials in Google Cloud Console."))
                else:
                    self.root.after(0, lambda: self.google_status_lbl.config(text=f"❌ Status Code {resp.status_code}", foreground="#d50000"))
            except Exception as ex:
                self.root.after(0, lambda: self.google_status_lbl.config(text="❌ Connection Failed", foreground="#d50000"))
        threading.Thread(target=_test, daemon=True).start()

    def test_groq_api_key(self):
        key = self.groq_api_entry.get().strip()
        if not key:
            messagebox.showwarning("Key Missing", "Please enter or paste your Groq AI API Key first.")
            return
        self.settings["groq_api_key"] = key
        self.auto_sync_settings()
        self.groq_status_lbl.config(text="🔄 Testing connection...", foreground="#f57c00")
        def _test():
            try:
                headers = {"Authorization": f"Bearer {key}"}
                resp = requests.get("https://api.groq.com/openai/v1/models", headers=headers, timeout=8)
                if resp.status_code == 200:
                    self.root.after(0, lambda: self.groq_status_lbl.config(text="✅ Groq Key Verified & Active!", foreground="#00c853"))
                    play_completion_chime("Ping")
                    self.root.after(0, lambda: messagebox.showinfo("Groq AI Key Valid", "Success! Your free Groq AI API Key is verified.\n\nFast AI email generation is active and ready to use in Tab 3!"))
                elif resp.status_code == 401:
                    self.root.after(0, lambda: self.groq_status_lbl.config(text="❌ Invalid Groq Key (401)", foreground="#d50000"))
                    self.root.after(0, lambda: messagebox.showerror("Invalid Groq Key", "The Groq API Key entered is invalid. Please copy your key from console.groq.com/keys and try again."))
                else:
                    self.root.after(0, lambda: self.groq_status_lbl.config(text=f"❌ Error {resp.status_code}", foreground="#d50000"))
            except Exception as ex:
                self.root.after(0, lambda: self.groq_status_lbl.config(text="❌ Connection Failed", foreground="#d50000"))
        threading.Thread(target=_test, daemon=True).start()

    def test_gmail_smtp(self):
        email = self.email_entry.get().strip()
        pwd = self.password_entry.get().strip()
        if not email or not pwd:
            messagebox.showwarning("Credentials Missing", "Please enter both your Gmail address and 16-character App Password.")
            return
        self.gmail_status_lbl.config(text="🔄 Testing...", foreground="#f57c00")
        def _test():
            try:
                server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
                server.starttls()
                server.login(email, pwd)
                server.quit()
                self.root.after(0, lambda: self.gmail_status_lbl.config(text="✅ Gmail SMTP Authenticated!", foreground="#00c853"))
                play_completion_chime("Ping")
                self.root.after(0, lambda: messagebox.showinfo("Gmail Login Valid", "Success! Authenticated successfully with Gmail SMTP.\n\nYou are ready to send cold outreach emails directly from your inbox."))
            except Exception as ex:
                self.root.after(0, lambda: self.gmail_status_lbl.config(text="❌ Authentication Failed", foreground="#d50000"))
                self.root.after(0, lambda: messagebox.showerror("Gmail SMTP Error", f"Could not authenticate with Gmail SMTP:\n\n{ex}\n\nMake sure 2-Step Verification is ON, and you are using a 16-character App Password from myaccount.google.com/apppasswords."))
        threading.Thread(target=_test, daemon=True).start()

    def save_settings(self):
        DEVELOPER_KEYS_BLACKLIST = {
            "AIzaSyCWnXaGL7ZGhBUzQHR43f4ybpXGbWZbric",
        }
        key = self.api_key_entry.get().strip() if hasattr(self, 'api_key_entry') else self.settings.get("api_key", "")
        if key in DEVELOPER_KEYS_BLACKLIST or "AIzaSyCWnXaGL7ZGhBUzQHR43f4ybpXGbWZbric" in key:
            key = ""
        self.settings["api_key"] = key
        if hasattr(self, 'email_entry'):
            self.settings["email"] = self.email_entry.get().strip()
        if hasattr(self, 'password_entry'):
            self.settings["password"] = self.password_entry.get().strip()
        if hasattr(self, 'groq_api_entry'):
            self.settings["groq_api_key"] = self.groq_api_entry.get().strip()
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(self.settings, f, indent=4)
            
    def notify_saved(self):
        self.save_settings()
        play_completion_chime("Ping")
        if hasattr(self, 'save_status_lbl'):
            self.save_status_lbl.config(text="✅ Configuration Successfully Saved & Active!", foreground="#00c853")
            def _revert():
                try:
                    self.save_status_lbl.config(text="Credentials stored locally and securely on your device.", foreground="#666666")
                except Exception:
                    pass
            self.root.after(2500, _revert)
        messagebox.showinfo("Saved", "Settings saved successfully!\nAll API keys and credentials are now active.")

    def reset_to_factory_defaults(self):
        if messagebox.askyesno("Reset All Configuration", "Are you sure you want to completely clear all saved API keys, SMTP credentials, and reset settings to default?\n\nThis will purge local settings on this device."):
            try:
                if os.path.exists(SETTINGS_FILE):
                    os.remove(SETTINGS_FILE)
            except Exception:
                pass
            self.settings = self.load_settings()
            if hasattr(self, 'api_key_entry'):
                self.api_key_entry.delete(0, tk.END)
                self.google_status_lbl.config(text="⚪ Not tested", foreground="#666666")
            if hasattr(self, 'groq_api_entry'):
                self.groq_api_entry.delete(0, tk.END)
                self.groq_status_lbl.config(text="⚪ Not tested", foreground="#666666")
            if hasattr(self, 'email_entry'):
                self.email_entry.delete(0, tk.END)
            if hasattr(self, 'password_entry'):
                self.password_entry.delete(0, tk.END)
                self.gmail_status_lbl.config(text="⚪ Not tested", foreground="#666666")
            self.auto_sync_settings()
            messagebox.showinfo("Reset Complete", "All credentials and local configuration have been cleared successfully.")

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except: pass
        return {}

    def save_history(self):
        with open(HISTORY_FILE, 'w') as f:
            json.dump(self.history, f)

    def setup_settings_tab(self):
        canvas = tk.Canvas(self.tab_settings, highlightthickness=0)
        if os.name == 'nt':
            canvas.configure(bg="#f4f6f9")
        scrollbar = ttk.Scrollbar(self.tab_settings, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # Header Title
        header_frame = ttk.Frame(scrollable_frame)
        header_frame.pack(fill='x', padx=30, pady=(25, 20))
        
        ttk.Label(header_frame, text="⚙️ System Configuration & Direct API Access", font=("Segoe UI", 18, "bold")).pack(anchor='w')
        ttk.Label(header_frame, text="Configure your Google Places and free Groq AI credentials below. Click the direct portal buttons to open each official dashboard instantly.", font=("Segoe UI", 11), foreground="#555555").pack(anchor='w', pady=(4, 0))

        # ================= CARD 1: GOOGLE PLACES API =================
        card_google = ttk.LabelFrame(scrollable_frame, text=" 🗺️ 1. Google Places API (Google Maps Scraping) ", padding=15)
        card_google.pack(fill='x', padx=30, pady=(0, 15))
        
        ttk.Label(card_google, text="Powers deep lead extraction from Google Maps with direct phone numbers, addresses, ratings, and websites.\nGoogle provides $200 free credit monthly (~10,000+ business searches free every month).\nEnter your own Google Cloud Places API key below. Credentials remain private and stored on your local device only.", font=("Segoe UI", 10)).pack(anchor='w', pady=(0, 8))
        
        g_url_frame = ttk.Frame(card_google)
        g_url_frame.pack(fill='x', pady=(0, 10))
        ttk.Label(g_url_frame, text="Direct Console URL:", font=("Segoe UI", 10, "bold")).pack(side='left', padx=(0, 6))
        g_link = ttk.Label(g_url_frame, text="https://console.cloud.google.com/google/maps-apis/credentials", font=("Segoe UI", 10, "underline"), foreground="#1976d2")
        g_link.bind("<Button-1>", lambda e: self.open_url("https://console.cloud.google.com/google/maps-apis/credentials"))
        g_link.pack(side='left', padx=(0, 15))
        ttk.Button(g_url_frame, text="🌐 Open Google Cloud Console", command=lambda: self.open_url("https://console.cloud.google.com/google/maps-apis/credentials"), style="Accent.TButton").pack(side='left')

        g_input_frame = ttk.Frame(card_google)
        g_input_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(g_input_frame, text="Places API Key:", font=("Segoe UI", 11, "bold")).pack(side='left', padx=(0, 20))
        self.api_key_entry = ttk.Entry(g_input_frame, width=42, font=("Segoe UI", 11))
        self.api_key_entry.insert(0, self.settings.get("api_key", ""))
        self.api_key_entry.pack(side='left', padx=(0, 6))
        self.api_key_entry.bind("<KeyRelease>", lambda e: self.auto_sync_settings())
        self.api_key_entry.bind("<FocusOut>", lambda e: self.auto_sync_settings())
        ttk.Button(g_input_frame, text="📋 Paste", command=lambda: self.paste_to_entry(self.api_key_entry)).pack(side='left', padx=3)
        ttk.Button(g_input_frame, text="⚡ Test Key", command=self.test_google_places_key).pack(side='left', padx=3)
        self.google_status_lbl = ttk.Label(g_input_frame, text="⚪ Not tested", font=("Segoe UI", 10, "bold"), foreground="#666666")
        self.google_status_lbl.pack(side='left', padx=10)

        ttk.Label(card_google, text="💡 Quick Steps: 1. Click 'Open Google Cloud Console' • 2. Click '+ CREATE CREDENTIALS' -> 'API Key' • 3. Enable 'Places API (New)' • 4. Paste key above & click 'Test Key'.", font=("Segoe UI", 9, "italic"), foreground="#666666").pack(anchor='w')

        # ================= CARD 2: GROQ AI API =================
        card_groq = ttk.LabelFrame(scrollable_frame, text=" 🤖 2. Groq AI API (100% Free Cold Email Pitch Generator) ", padding=15)
        card_groq.pack(fill='x', padx=30, pady=(0, 15))
        
        ttk.Label(card_groq, text="Powers instant high-converting cold email generation in Tab 3 using ultra-fast Groq AI models.\n100% Free forever with no credit card required.", font=("Segoe UI", 10)).pack(anchor='w', pady=(0, 8))
        
        groq_url_frame = ttk.Frame(card_groq)
        groq_url_frame.pack(fill='x', pady=(0, 10))
        ttk.Label(groq_url_frame, text="Direct Console URL:", font=("Segoe UI", 10, "bold")).pack(side='left', padx=(0, 6))
        groq_link = ttk.Label(groq_url_frame, text="https://console.groq.com/keys", font=("Segoe UI", 10, "underline"), foreground="#1976d2")
        groq_link.bind("<Button-1>", lambda e: self.open_url("https://console.groq.com/keys"))
        groq_link.pack(side='left', padx=(0, 15))
        ttk.Button(groq_url_frame, text="🌐 Open Free Groq Console", command=lambda: self.open_url("https://console.groq.com/keys"), style="Accent.TButton").pack(side='left')

        groq_input_frame = ttk.Frame(card_groq)
        groq_input_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(groq_input_frame, text="Groq AI API Key:", font=("Segoe UI", 11, "bold")).pack(side='left', padx=(0, 18))
        self.groq_api_entry = ttk.Entry(groq_input_frame, width=42, font=("Segoe UI", 11))
        self.groq_api_entry.insert(0, self.settings.get("groq_api_key", ""))
        self.groq_api_entry.pack(side='left', padx=(0, 6))
        self.groq_api_entry.bind("<KeyRelease>", lambda e: self.auto_sync_settings())
        self.groq_api_entry.bind("<FocusOut>", lambda e: self.auto_sync_settings())
        ttk.Button(groq_input_frame, text="📋 Paste", command=lambda: self.paste_to_entry(self.groq_api_entry)).pack(side='left', padx=3)
        ttk.Button(groq_input_frame, text="⚡ Test Key", command=self.test_groq_api_key).pack(side='left', padx=3)
        self.groq_status_lbl = ttk.Label(groq_input_frame, text="⚪ Not tested", font=("Segoe UI", 10, "bold"), foreground="#666666")
        self.groq_status_lbl.pack(side='left', padx=10)

        ttk.Label(card_groq, text="💡 Quick Steps: 1. Click 'Open Free Groq Console' • 2. Sign in free with Google/GitHub • 3. Click 'Create API Key' • 4. Copy the key (starts with 'gsk_') and paste above.", font=("Segoe UI", 9, "italic"), foreground="#666666").pack(anchor='w')

        # ================= CARD 3: GMAIL SMTP SENDER =================
        card_gmail = ttk.LabelFrame(scrollable_frame, text=" ✉️ 3. Gmail Cold Outreach Account (SMTP Sender) ", padding=15)
        card_gmail.pack(fill='x', padx=30, pady=(0, 15))
        
        ttk.Label(card_gmail, text="Allows sending personalized 1-on-1 and bulk cold emails directly from your Gmail address without paying SaaS outreach tools.", font=("Segoe UI", 10)).pack(anchor='w', pady=(0, 8))
        
        gmail_url_frame = ttk.Frame(card_gmail)
        gmail_url_frame.pack(fill='x', pady=(0, 10))
        ttk.Label(gmail_url_frame, text="Direct Passwords URL:", font=("Segoe UI", 10, "bold")).pack(side='left', padx=(0, 6))
        gmail_link = ttk.Label(gmail_url_frame, text="https://myaccount.google.com/apppasswords", font=("Segoe UI", 10, "underline"), foreground="#1976d2")
        gmail_link.bind("<Button-1>", lambda e: self.open_url("https://myaccount.google.com/apppasswords"))
        gmail_link.pack(side='left', padx=(0, 15))
        ttk.Button(gmail_url_frame, text="🌐 Open Gmail App Passwords", command=lambda: self.open_url("https://myaccount.google.com/apppasswords")).pack(side='left')

        gm_r1 = ttk.Frame(card_gmail)
        gm_r1.pack(fill='x', pady=(0, 6))
        ttk.Label(gm_r1, text="Gmail Address:", font=("Segoe UI", 11, "bold")).pack(side='left', padx=(0, 31))
        self.email_entry = ttk.Entry(gm_r1, width=42, font=("Segoe UI", 11))
        self.email_entry.insert(0, self.settings.get("email", ""))
        self.email_entry.pack(side='left', padx=(0, 6))
        self.email_entry.bind("<KeyRelease>", lambda e: self.auto_sync_settings())
        self.email_entry.bind("<FocusOut>", lambda e: self.auto_sync_settings())
        ttk.Button(gm_r1, text="📋 Paste", command=lambda: self.paste_to_entry(self.email_entry)).pack(side='left', padx=3)

        gm_r2 = ttk.Frame(card_gmail)
        gm_r2.pack(fill='x', pady=(0, 8))
        ttk.Label(gm_r2, text="16-Char App Password:", font=("Segoe UI", 11, "bold")).pack(side='left', padx=(0, 4))
        self.password_entry = ttk.Entry(gm_r2, width=42, font=("Segoe UI", 11), show="•")
        self.password_entry.insert(0, self.settings.get("password", ""))
        self.password_entry.pack(side='left', padx=(0, 6))
        self.password_entry.bind("<KeyRelease>", lambda e: self.auto_sync_settings())
        self.password_entry.bind("<FocusOut>", lambda e: self.auto_sync_settings())

        self.show_pwd_btn = ttk.Button(gm_r2, text="👁️ Show", command=self.toggle_password_visibility)
        self.show_pwd_btn.pack(side='left', padx=3)
        ttk.Button(gm_r2, text="📋 Paste", command=lambda: self.paste_to_entry(self.password_entry)).pack(side='left', padx=3)
        ttk.Button(gm_r2, text="⚡ Test Login", command=self.test_gmail_smtp).pack(side='left', padx=3)
        self.gmail_status_lbl = ttk.Label(gm_r2, text="⚪ Not tested", font=("Segoe UI", 10, "bold"), foreground="#666666")
        self.gmail_status_lbl.pack(side='left', padx=10)

        ttk.Label(card_gmail, text="💡 How to get it: 1. Turn ON 2-Step Verification on your Google Account • 2. Click 'Open Gmail App Passwords' • 3. Generate a 16-character App Password • 4. Paste it above.", font=("Segoe UI", 9, "italic"), foreground="#666666").pack(anchor='w')

        # ================= SAVE & RESET CONFIGURATION ROW =================
        save_frame = ttk.Frame(scrollable_frame)
        save_frame.pack(fill='x', padx=30, pady=(10, 30))
        
        save_btn = ttk.Button(save_frame, text="💾 Save All Configuration", command=self.notify_saved, style="Accent.TButton")
        save_btn.pack(side='left', padx=(0, 10))

        reset_btn = ttk.Button(save_frame, text="🗑️ Reset All Configuration", command=self.reset_to_factory_defaults)
        reset_btn.pack(side='left', padx=(0, 15))
        
        self.save_status_lbl = ttk.Label(save_frame, text="Credentials stored locally and securely on your device.", font=("Segoe UI", 10), foreground="#666666")
        self.save_status_lbl.pack(side='left')


if __name__ == "__main__":
    root = tk.Tk()
    app = NexusHarvesterApp(root)
    root.mainloop()
