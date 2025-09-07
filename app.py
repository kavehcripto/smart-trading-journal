# app.py
import streamlit as st
import sqlite3
import json
from datetime import datetime
import arabic_reshaper
from bidi.algorithm import get_display

# --- session_state ---
if 'pre_trade_data' not in st.session_state:
    st.session_state.pre_trade_data = {}

# --- پشتیبانی از فارسی ---
def fa(text):
    try:
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)
    except:
        return str(text)

def html_rtl(text):
    try:
        reshaped = arabic_reshaper.reshape(str(text))
        display = get_display(reshaped)
    except:
        display = str(text)
    return f'<div dir="rtl" style="font-family: Tahoma, sans-serif; font-size: 16px; text-align: right;">{display}</div>'

# --- اتصال به دیتابیس ---
def connect_db():
    return sqlite3.connect('journal.db')

def create_tables(conn):
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            entry_price REAL,
            exit_price REAL,
            side TEXT,
            qty REAL,
            risk REAL,
            trade_type TEXT,
            leverage REAL,
            psychological_tags TEXT,
            market_context TEXT,
            strategy_id INTEGER,
            profit_or_loss REAL,
            rr_calculated REAL,
            trade_date TEXT,
            strategy_compliance_rate REAL,
            strategy_missing_rules TEXT
        );
        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            description TEXT,
            entry_rules TEXT,
            exit_rules TEXT,
            created_at TEXT
        );
    """)
    conn.commit()

# --- محاسبه PnL و R:R ---
def calculate_pnl_and_rr(trade_data):
    entry = trade_data.get("entry_price", 0)
    exit_p = trade_data.get("exit_price", 0)
    qty = trade_data.get("qty", 0)
    side = (trade_data.get("side") or "").lower()
    risk = trade_data.get("risk", 0)
    leverage = trade_data.get("leverage", 1.0)
    trade_type = trade_data.get("trade_type", "spot")

    if side == "buy":
        pnl = (exit_p - entry) * qty * (leverage if trade_type == "futures" else 1)
    elif side == "sell":
        pnl = (entry - exit_p) * qty * (leverage if trade_type == "futures" else 1)
    else:
        return 0, 0

    rr = pnl / risk if risk > 0 else 0
    return round(pnl, 2), round(rr, 2)

# --- بارگذاری معاملات ---
def load_trades(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades ORDER BY trade_date DESC")
    rows = cur.fetchall()
    trades = []
    for r in rows:
        trade = {
            "id": r[0], "symbol": r[1], "entry_price": r[2], "exit_price": r[3],
            "side": r[4], "qty": r[5], "risk": r[6], "trade_type": r[7],
            "leverage": r[8], "market_context": r[10],
            "profit_or_loss": r[12], "rr_calculated": r[13], "trade_date": r[14],
            "strategy_id": r[11],
            "strategy_compliance_rate": r[15],
            "strategy_missing_rules": r[16]
        }
        try:
            trade["psychological_tags"] = json.loads(r[9]) if r[9] else []
        except:
            trade["psychological_tags"] = []
        trades.append(trade)
    return trades

# --- ذخیره معامله ---
def save_trade(conn, data):
    tags_json = json.dumps(data.get("psychological_tags", []), ensure_ascii=False)
    missing_json = json.dumps(data.get("strategy_missing_rules", []), ensure_ascii=False)
    date = data.get("trade_date") or datetime.now().isoformat()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO trades (symbol, entry_price, exit_price, side, qty, risk,
                            trade_type, leverage, psychological_tags,
                            market_context, strategy_id, profit_or_loss,
                            rr_calculated, trade_date, strategy_compliance_rate,
                            strategy_missing_rules)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data["symbol"], data["entry_price"], data["exit_price"], data["side"],
        data["qty"], data["risk"], data["trade_type"], data["leverage"],
        tags_json, data.get("market_context"), data.get("strategy_id"),
        data["profit_or_loss"], data["rr_calculated"], date,
        data.get("strategy_compliance_rate"),
        missing_json
    ))
    conn.commit()

# --- بارگذاری استراتژی‌ها ---
def load_strategies(conn):
    cur = conn.cursor()
    cur.execute("SELECT * FROM strategies ORDER BY name")
    rows = cur.fetchall()
    strategies = []
    for r in rows:
        try:
            entry_rules = json.loads(r[3]) if r[3] else []
            exit_rules = json.loads(r[4]) if r[4] else []
        except:
            entry_rules = []
            exit_rules = []
        strategies.append({
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "entry_rules": entry_rules,
            "exit_rules": exit_rules,
            "created_at": r[5]
        })
    return strategies

# --- ذخیره استراتژی ---
def save_strategy(conn, strategy_data):
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO strategies (name, description, entry_rules, exit_rules, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            strategy_data['name'],
            strategy_data['description'],
            json.dumps(strategy_data['entry_rules'], ensure_ascii=False),
            json.dumps(strategy_data['exit_rules'], ensure_ascii=False),
            datetime.now().isoformat()
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # اسم تکراری

# ================================
# 🔍 تشخیص الگوی رفتاری
# ================================

def learn_user_pattern(trades, lookback=5):
    if len(trades) < 3:
        return None
    recent = trades[:lookback]
    
    symbols = [t['symbol'] for t in recent]
    sides = [t['side'] for t in recent]
    types = [t['trade_type'] for t in recent]
    leverages = [t['leverage'] for t in recent]
    contexts = [t.get('market_context') or 'not_set' for t in recent]
    tags = [tag for t in recent for tag in t.get('psychological_tags', [])]

    return {
        'common_symbols': set(symbols),
        'common_side': max(set(sides), key=sides.count),
        'common_type': max(set(types), key=types.count),
        'avg_leverage': sum(leverages) / len(leverages),
        'common_contexts': set(contexts),
        'common_tags': set(tags),
    }

def check_deviation(new_trade, pattern):
    if not pattern:
        return 0.0
    score = 0
    total = 0

    total += 1
    if new_trade['symbol'] not in pattern['common_symbols']:
        score += 1

    total += 1
    if new_trade['side'] != pattern['common_side']:
        score += 1

    total += 1
    if new_trade['trade_type'] != pattern['common_type']:
        score += 1

    total += 1
    if abs(new_trade['leverage'] - pattern['avg_leverage']) > pattern['avg_leverage'] * 0.8:
        score += 1

    total += 1
    current_ctx = new_trade.get('market_context') or 'not_set'
    if current_ctx not in pattern['common_contexts']:
        score += 1

    total += 1
    new_tags = set(new_trade.get('psychological_tags', []))
    if not (new_tags & pattern['common_tags']):
        score += 1

    return score / total

# ================================
# 🚀 تکامل رفتاری (Behavioral Evolution)
# ================================

def analyze_evolution(trades):
    if len(trades) < 8:
        return None
        
    mid = len(trades) // 2
    early = trades[mid:]   # اول دوره
    recent = trades[:mid]  # آخر دوره
    
    def get_behavioral_score(trade_list):
        score = 0
        for t in trade_list:
            tags = t.get('psychological_tags', [])
            hour = datetime.fromisoformat(t['trade_date']).hour
            if 'revenge' in tags or 'انتقام' in tags:
                score += 2
            if 'FOMO' in tags or 'fomo' in tags or 'هیجان' in tags:
                score += 1.5
            if 'fear' in tags or 'ترس' in tags:
                score += 1
            if 2 <= hour <= 5:
                score += 1
        return score / len(trade_list) if trade_list else 0

    early_score = get_behavioral_score(early)
    recent_score = get_behavioral_score(recent)
    
    if early_score == 0:
        improvement = 100.0
    else:
        improvement = ((early_score - recent_score) / early_score) * 100

    return {
        "improvement": improvement,
        "early_avg_rr": avg(t['rr_calculated'] for t in early if t['profit_or_loss'] > 0),
        "recent_avg_rr": avg(t['rr_calculated'] for t in recent if t['profit_or_loss'] > 0),
        "trend": "improving" if improvement > 15 else "needs_attention"
    }

# --- میانگین ---
def avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0

# ================================
# 📊 تحلیل عملکرد بر اساس استراتژی
# ================================

def analyze_strategy_performance(trades):
    """تحلیل عملکرد معاملات بر اساس استراتژی"""
    if len(trades) == 0:
        return []

    strategy_data = {}
    for t in trades:
        sid = t.get('strategy_id') or 'no_strategy'
        name = f"Strategy {t['strategy_id']}" if t['strategy_id'] else "No Strategy"
        
        if sid not in strategy_data:
            strategy_data[sid] = {
                "name": name,
                "pnl": 0,
                "rr_sum": 0,
                "count": 0,
                "wins": 0,
                "losses": 0
            }
        
        strategy_data[sid]["pnl"] += t["profit_or_loss"]
        strategy_data[sid]["rr_sum"] += t["rr_calculated"]
        strategy_data[sid]["count"] += 1
        if t["profit_or_loss"] > 0:
            strategy_data[sid]["wins"] += 1
        else:
            strategy_data[sid]["losses"] += 1

    results = []
    for sid, data in strategy_data.items():
        avg_rr = data["rr_sum"] / data["count"] if data["count"] > 0 else 0
        win_rate = data["wins"] / data["count"] if data["count"] > 0 else 0
        
        results.append({
            "strategy_name": data["name"],
            "total_pnl": round(data["pnl"], 2),
            "avg_rr": round(avg_rr, 2),
            "win_rate": round(win_rate, 2),
            "trade_count": data["count"],
            "wins": data["wins"],
            "losses": data["losses"]
        })
    
    return sorted(results, key=lambda x: x["total_pnl"], reverse=True)

# ================================
# 🔀 تشخیص تغییر استراتژی
# ================================

def detect_strategy_change(trades):
    """آیا کاربر استراتژی خودش رو تغییر داده؟"""
    if len(trades) < 5:
        return None
        
    first = trades[-5:]  # اول دوره
    last = trades[:5]   # آخر دوره
    
    first_strategies = [t.get('strategy_id') for t in first if t.get('strategy_id')]
    last_strategies = [t.get('strategy_id') for t in last if t.get('strategy_id')]
    
    if not first_strategies or not last_strategies:
        return None
        
    first_mode = max(set(first_strategies), key=first_strategies.count)
    last_mode = max(set(last_strategies), key=last_strategies.count)
    
    if first_mode != last_mode:
        return {
            "changed": True,
            "from": f"Strategy {first_mode}",
            "to": f"Strategy {last_mode}"
        }
    return {"changed": False}

# ================================
# 🔤 لیست نمادهای اخیر
# ================================

def get_recent_symbols(trades, limit=10):
    """لیست نمادهای اخیر را برمی‌گرداند"""
    symbols = [t['symbol'] for t in trades if t['symbol']]
    seen = set()
    unique = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:limit]

# ================================
# 🎨 UI اصلی
# ================================

st.set_page_config(page_title="Smart Trading Journal", layout="centered")

# --- تنظیمات در sidebar ---
with st.sidebar:
    st.header("⚙️ Settings")
    language = st.selectbox("Language", ["English", "فارسی"], index=0)
    user_name = st.text_input("Your Name" if language == "English" else "نام شما", "Trader")
    currency = st.selectbox("Currency", ["$", "€", "ت"], index=0)

# --- ترجمه متن‌ها ---
if language == "English":
    def t(text): return text
    user_greeting = f"Hi, {user_name}!"
else:
    def t(text):
        translations = {
            "Hi, {name}!": f"سلام، {user_name}!",
            "Smart Trading Journal": "دفترچه معاملات هوشمند",
            "Check before you trade, not after you lose": "قبل از ورود هشدار بگیر، نه بعد از ضرر",
            "Pre-Trade Check": "بررسی قبل از ورود",
            "Record Trade": "ثبت معامله",
            "Smart Report": "گزارش هوشمند",
            "Define Strategy": "تعریف استراتژی",
            "Are you sure you want to enter?": "آیا واقعاً می‌خواهی وارد شوی؟",
            "Record New Trade": "ثبت معامله جدید",
            "Record Trade": "ثبت معامله",
            "Total PnL": "سود کل",
            "Win Rate": "درصد برنده",
            "Your Behavioral Pattern": "الگوی رفتاری شما",
            "Common Symbols": "نمادهای معمول",
            "Preferred Side": "جهت ترجیحی",
            "Common Type": "نوع معامله",
            "Avg Leverage": "لوریج متوسط",
            "Preferred Context": "محیط بازار ترجیحی",
            "Common Emotions": "احساسات رایج",
            "Recent Trades": "معاملات اخیر",
            "Please fill in required fields.": "لطفاً فیلدهای ضروری را پر کنید.",
            "Trade recorded!": "معامله ثبت شد!",
            "PnL": "سود/ضرر",
            "R:R": "R:R",
            "Symbol": "نماد",
            "Entry Price": "قیمت ورود",
            "Exit Price": "قیمت خروج",
            "Side": "جهت",
            "Quantity": "حجم",
            "Risk ($)": "ریسک ($)",
            "Trade Type": "نوع معامله",
            "Leverage": "لوریج",
            "Psychological Tags (comma-separated)": "برچسب‌های روانی (با کاما)",
            "Market Context": "محیط بازار",
            "Strategy ID (optional)": "شناسه استراتژی (اختیاری)",
            "Using": "استفاده از",
            "No Strategy": "بدون استراتژی",
            "Behavioral Evolution": "تکامل رفتاری",
            "Improvement": "بهبود",
            "Early Avg R:R": "میانگین R:R اولیه",
            "Recent Avg R:R": "میانگین R:R اخیر",
            "Great progress!": "پیشرفت عالی!",
            "Keep going!": "ادامه بده!",
            "Data saved! Go to 'Record Trade' to finalize.": "داده ذخیره شد! به 'ثبت معامله' برو تا کاملش کنی.",
            "✅ Data saved!": "✅ داده ذخیره شد!",
            "Strategy Name": "نام استراتژی",
            "Description": "توضیحات",
            "Entry Rules": "قوانین ورود",
            "Exit Rules": "قوانین خروج",
            "Condition": "شرط",
            "Required": "الزامی",
            "Save Strategy": "ذخیره استراتژی",
            "Strategy saved successfully!": "استراتژی با موفقیت ذخیره شد!",
            "Select Strategy": "انتخاب استراتیجی",
            "Strategy Compliance": "وفاداری به استراتژی",
            "Rule": "قانون",
            "Met": "اجرا شد",
            "Other": "سایر",
            "Enter Symbol": "نام نماد را وارد کنید",
            "Performance by Strategy": "عملکرد بر اساس استراتژی",
            "Total PnL": "سود کل",
            "Avg R:R": "میانگین R:R",
            "Win Rate": "درصد برنده",
            "You changed strategy": "استراتژی تو عوض شد",
            "The new strategy is performing better!": "استراتژی جدید عملکرد بهتری داره!",
            "The new strategy needs adjustment.": "استراتژی جدید نیاز به اصلاح داره.",
            "This strategy name already exists.": "این نام استراتژی قبلاً وجود دارد.",
            "Update Strategy": "به‌روزرسانی استراتژی",
            "Strategy updated successfully!": "استراتژی با موفقیت به‌روزرسانی شد!"
        }
        return translations.get(text, text)
    user_greeting = t(f"Hi, {user_name}!")

# --- CSS برای RTL فارسی ---
if language == "فارسی":
    st.markdown("""
    <style>
        body { direction: rtl; text-align: right; }
    </style>
    """, unsafe_allow_html=True)

# --- عنوان ---
if language == "فارسی":
    st.markdown(html_rtl("🧠 دفترچه معاملات هوشمند"), unsafe_allow_html=True)
    st.markdown(html_rtl("قبل از ورود هشدار بگیر، نه بعد از ضرر"), unsafe_allow_html=True)
else:
    st.title("🧠 Smart Trading Journal")
    st.caption("Check before you trade, not after you lose")

conn = connect_db()
create_tables(conn)
trades = load_trades(conn)
strategies = load_strategies(conn)
recent_symbols = get_recent_symbols(trades)
pattern = learn_user_pattern(trades)
evolution = analyze_evolution(trades)
strategy_perf = analyze_strategy_performance(trades)
strategy_change = detect_strategy_change(trades)

# --- منو ---
menu = st.radio(
    "",
    [t("Pre-Trade Check"), t("Record Trade"), t("Define Strategy"), t("Smart Report")],
    horizontal=True,
    label_visibility="collapsed"
)

# ================================
# ۱. بررسی قبل از ورود
# ================================
if menu == t("Pre-Trade Check"):
    if language == "فارسی":
        st.subheader(html_rtl("⚠️ آیا واقعاً می‌خواهی وارد شوی؟"))
    else:
        st.subheader("⚠️ Are you sure you want to enter?")

    with st.form("pre_trade_check"):
        col1, col2 = st.columns(2)
        with col1:
            # --- نماد با پیشنهادهای اخیر ---
            all_symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT"]
            all_symbols.extend(recent_symbols)
            unique_symbols = list(dict.fromkeys(all_symbols))
            symbol_options = ["[سایر]" if language == "فارسی" else "[Other]"] + unique_symbols
            selected_symbol = st.selectbox(t("Symbol"), options=symbol_options, index=0)
            if selected_symbol == ("[سایر]" if language == "فارسی" else "[Other]"):
                symbol = st.text_input(t("Enter Symbol"), placeholder="e.g. DOTUSDT")
            else:
                symbol = selected_symbol

            entry_price = st.number_input(t("Entry Price"), min_value=0.0, step=0.0001)
            qty = st.number_input(t("Quantity"), min_value=0.0, step=0.0001)
            trade_type = st.selectbox(t("Trade Type"), ["spot", "futures"])
        with col2:
            side = st.selectbox(t("Side"), ["buy", "sell"])
            risk = st.number_input(t("Risk ($)"), min_value=0.0, step=0.01)
            leverage = st.number_input(t("Leverage"), min_value=1.0, value=1.0, step=0.1)
            market_context = st.text_input(t("Market Context"), placeholder=t("trending, ranging, news"))

        psychological_tags = st.text_input(
            t("Psychological Tags (comma-separated)"),
            placeholder=t("patience, greed, FOMO, fear")
        )

        submitted = st.form_submit_button(t("✅ Check Behavior"))

        if submitted:
            if not symbol or entry_price == 0 or qty == 0:
                if language == "فارسی":
                    st.error(html_rtl("❌ لطفاً فیلدهای ضروری را پر کنید."))
                else:
                    st.error("❌ Please fill in required fields.")
            else:
                tags_list = [t.strip() for t in psychological_tags.split(",") if t.strip()]
                st.session_state.pre_trade_data = {
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "qty": qty,
                    "side": side,
                    "risk": risk,
                    "leverage": leverage,
                    "trade_type": trade_type,
                    "market_context": market_context,
                    "psychological_tags": tags_list
                }
                if language == "فارسی":
                    st.success(html_rtl("✅ داده ذخیره شد! به 'ثبت معامله' برو تا کاملش کنی."))
                else:
                    st.success("✅ Data saved! Go to 'Record Trade' to finalize.")

# ================================
# ۲. ثبت معامله
# ================================
elif menu == t("Record Trade"):
    if language == "فارسی":
        st.subheader(html_rtl("📝 ثبت معامله جدید"))
    else:
        st.subheader("📝 Record New Trade")

    with st.form("trade_form"):
        col1, col2 = st.columns(2)
        pre_data = st.session_state.pre_trade_data
        
        with col1:
            # --- نماد با پیشنهادهای اخیر ---
            all_symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT"]
            all_symbols.extend(recent_symbols)
            unique_symbols = list(dict.fromkeys(all_symbols))
            symbol_options = ["[سایر]" if language == "فارسی" else "[Other]"] + unique_symbols
            selected_symbol = st.selectbox(
                t("Symbol"), 
                options=symbol_options, 
                index=symbol_options.index(pre_data.get("symbol", "")) if pre_data.get("symbol") in symbol_options else 0
            )
            if selected_symbol == ("[سایر]" if language == "فارسی" else "[Other]"):
                symbol = st.text_input(t("Enter Symbol"), value="", placeholder="e.g. DOTUSDT")
            else:
                symbol = selected_symbol

            entry_price = st.number_input(t("Entry Price"), 
                              min_value=0.0, 
                              step=0.0001, 
                              value=float(pre_data.get("entry_price", 0.0)))
            qty = st.number_input(t("Quantity"), 
                  min_value=0.0, 
                  step=0.0001, 
                  value=float(pre_data.get("qty", 0.0)))
            trade_type = st.selectbox(t("Trade Type"), 
                      ["spot", "futures"], 
                      index=0 if pre_data.get("trade_type") != "futures" else 1)
        with col2:
            side = st.selectbox(t("Side"), 
                    ["buy", "sell"], 
                    index=0 if pre_data.get("side") != "sell" else 1)
            exit_price = st.number_input(t("Exit Price"), min_value=0.0, step=0.0001)
            risk = st.number_input(t("Risk ($)"), 
                   min_value=0.0, 
                   step=0.01, 
                   value=float(pre_data.get("risk", 0.0)))
            leverage = st.number_input(t("Leverage"), 
                           min_value=1.0, 
                           value=float(pre_data.get("leverage", 1.0)), 
                           step=0.1)

        psychological_tags = st.text_input(
            t("Psychological Tags (comma-separated)"),
            value=", ".join(pre_data.get("psychological_tags", [])),
            placeholder=t("patience, greed, FOMO")
        )
        market_context = st.text_input(t("Market Context"), 
                           value=pre_data.get("market_context", ""), 
                           placeholder=t("trending, ranging"))

        # --- انتخاب استراتژی ---
        strategy_names = ["No Strategy"] + [s['name'] for s in strategies]
        selected_strategy_name = st.selectbox(t("Select Strategy"), strategy_names)
        
        selected_strategy = None
        if selected_strategy_name != "No Strategy":
            for s in strategies:
                if s['name'] == selected_strategy_name:
                    selected_strategy = s
                    break

        submitted = st.form_submit_button(t("✅ Record Trade"))

        if submitted:
            if not symbol or entry_price == 0 or exit_price == 0 or qty == 0:
                if language == "فارسی":
                    st.error(html_rtl("❌ لطفاً فیلدهای ضروری را پر کنید."))
                else:
                    st.error("❌ Please fill in required fields.")
            else:
                tags_list = [t.strip() for t in psychological_tags.split(",") if t.strip()]
                data = {
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "side": side,
                    "qty": qty,
                    "risk": risk,
                    "trade_type": trade_type,
                    "leverage": leverage,
                    "psychological_tags": tags_list,
                    "market_context": market_context,
                    "strategy_id": selected_strategy['id'] if selected_strategy else None
                }
                pnl, rr = calculate_pnl_and_rr(data)
                data["profit_or_loss"] = pnl
                data["rr_calculated"] = rr

                # بررسی وفاداری به استراتژی
                if selected_strategy:
                    compliance_data = {}
                    st.markdown("### " + t("Strategy Compliance"))
                    for rule in selected_strategy['entry_rules']:
                        fulfilled = st.checkbox(f"{rule['condition']} ({t('Required') if rule['required'] else 'Optional'})", key=rule['condition'])
                        compliance_data[rule['condition']] = fulfilled
                    
                    total_rules = len(selected_strategy['entry_rules'])
                    met_rules = sum(1 for v in compliance_data.values() if v)
                    compliance_rate = met_rules / total_rules if total_rules else 0
                    missing_rules = [r['condition'] for r in selected_strategy['entry_rules'] if not compliance_data[r['condition']]]

                    data["strategy_compliance_rate"] = compliance_rate
                    data["strategy_missing_rules"] = missing_rules

                    st.success(f"✅ {t('Strategy Compliance')}: {compliance_rate:.0%}")

                save_trade(conn, data)
                st.session_state.pre_trade_data = {}
                if language == "فارسی":
                    st.success(html_rtl(f"✅ معامله ثبت شد! | {t('PnL')}: {pnl}{currency} | {t('R:R')}: {rr}"))
                else:
                    st.success(f"✅ {t('Trade recorded!')} | {t('PnL')}: {pnl}{currency} | {t('R:R')}: {rr}")

# ================================
# ۳. تعریف استراتژی
# ================================
elif menu == t("Define Strategy"):
    if language == "فارسی":
        st.subheader(html_rtl("➕ تعریف استراتژی"))
    else:
        st.subheader("➕ Define a New Strategy")

    # --- لیست استراتژی‌ها ---
    strategy_names = [s['name'] for s in strategies]
    action = st.radio(t("Action"), [t("Create New Strategy"), t("Edit Existing Strategy")])

    if action == t("Create New Strategy"):
        name = st.text_input(t("Strategy Name"))
        desc = st.text_area(t("Description"))

        st.markdown("---")
        if language == "فارسی":
            st.markdown(html_rtl("### 🔽 قوانین ورود"), unsafe_allow_html=True)
        else:
            st.write("### 🔽 Entry Rules")

        entry_rules = []
        for i in range(5):
            col1, col2 = st.columns([3, 2])
            with col1:
                condition = st.text_input(t("Condition"), key=f"new_entry_cond_{i}")
            with col2:
                req = st.checkbox(t("Required"), value=True, key=f"new_entry_req_{i}")
            if condition:
                entry_rules.append({"condition": condition, "required": req})

        st.markdown("---")
        if language == "فارسی":
            st.markdown(html_rtl("### 🔼 قوانین خروج"), unsafe_allow_html=True)
        else:
            st.write("### 🔼 Exit Rules")

        exit_rules = []
        for i in range(5):
            col1, col2 = st.columns([3, 2])
            with col1:
                condition = st.text_input(t("Condition"), key=f"new_exit_cond_{i}")
            with col2:
                req = st.checkbox(t("Required"), value=True, key=f"new_exit_req_{i}")
            if condition:
                exit_rules.append({"condition": condition, "required": req})

        if st.button(t("Save Strategy")):
            if not name or not entry_rules:
                st.error(t("Please fill in required fields."))
            elif name in strategy_names:
                st.error(t("This strategy name already exists."))
            else:
                strategy_data = {
                    "name": name,
                    "description": desc,
                    "entry_rules": entry_rules,
                    "exit_rules": exit_rules
                }
                success = save_strategy(conn, strategy_data)
                if success:
                    st.success(t("Strategy saved successfully!"))
                    st.experimental_rerun()
                else:
                    st.error(t("This strategy name already exists."))

    else:
        selected_name = st.selectbox(t("Select Strategy"), strategy_names)
        selected_strategy = next((s for s in strategies if s['name'] == selected_name), None)
        if selected_strategy:
            with st.form("edit_strategy"):
                name = st.text_input(t("Strategy Name"), value=selected_strategy['name'])
                desc = st.text_area(t("Description"), value=selected_strategy['description'])

                st.markdown("---")
                if language == "فارسی":
                    st.markdown(html_rtl("### 🔽 قوانین ورود"), unsafe_allow_html=True)
                else:
                    st.write("### 🔽 Entry Rules")

                for i, rule in enumerate(selected_strategy['entry_rules']):
                    col1, col2 = st.columns([3, 2])
                    with col1:
                        condition = st.text_input(t("Condition"), value=rule['condition'], key=f"edit_entry_{i}")
                    with col2:
                        req = st.checkbox(t("Required"), value=rule['required'], key=f"edit_req_{i}")

                st.markdown("---")
                if language == "فارسی":
                    st.markdown(html_rtl("### 🔼 قوانین خروج"), unsafe_allow_html=True)
                else:
                    st.write("### 🔼 Exit Rules")

                for i, rule in enumerate(selected_strategy['exit_rules']):
                    col1, col2 = st.columns([3, 2])
                    with col1:
                        condition = st.text_input(t("Condition"), value=rule['condition'], key=f"edit_exit_{i}")
                    with col2:
                        req = st.checkbox(t("Required"), value=rule['required'], key=f"edit_exit_req_{i}")

                submitted = st.form_submit_button(t("Update Strategy"))
                if submitted:
                    if not name:
                        st.error(t("Please fill in required fields."))
                    elif name != selected_strategy['name'] and name in strategy_names:
                        st.error(t("This strategy name already exists."))
                    else:
                        selected_strategy['name'] = name
                        selected_strategy['description'] = desc
                        selected_strategy['entry_rules'] = [{"condition": st.session_state[f"edit_entry_{i}"], "required": st.session_state[f"edit_req_{i}"]} for i in range(len(selected_strategy['entry_rules']))]
                        selected_strategy['exit_rules'] = [{"condition": st.session_state[f"edit_exit_{i}"], "required": st.session_state[f"edit_exit_req_{i}"]} for i in range(len(selected_strategy['exit_rules']))]
                        save_strategy(conn, selected_strategy)
                        st.success(t("Strategy updated successfully!"))
                        st.experimental_rerun()

# ================================
# ۴. گزارش هوشمند
# ================================
elif menu == t("Smart Report"):
    if len(trades) == 0:
        if language == "فارسی":
            st.info(html_rtl("📭 هنوز معامله‌ای ثبت نشده."))
        else:
            st.info("📭 No trades recorded yet.")
    else:
        if language == "فارسی":
            st.subheader(html_rtl(f"📊 گزارش — {len(trades)} معامله"))
        else:
            st.subheader(f"📊 Report — {len(trades)} Trades")
        
        total_pnl = sum(t['profit_or_loss'] for t in trades)
        wins = [t for t in trades if t['profit_or_loss'] > 0]
        win_rate = len(wins) / len(trades) if trades else 0
        
        col1, col2 = st.columns(2)
        col1.metric(t("Total PnL"), f"{total_pnl:.2f} {currency}")
        col2.metric(t("Win Rate"), f"{win_rate:.1%}")
        
        if pattern:
            if language == "فارسی":
                st.markdown(html_rtl("### 🧠 الگوی رفتاری شما"), unsafe_allow_html=True)
                st.write(html_rtl(f"• {t('Common Symbols')}: {', '.join(pattern['common_symbols'])}"))
                st.write(html_rtl(f"• {t('Preferred Side')}: {pattern['common_side'].upper()}"))
                st.write(html_rtl(f"• {t('Common Type')}: {pattern['common_type']}"))
                st.write(html_rtl(f"• {t('Avg Leverage')}: {pattern['avg_leverage']:.1f}x"))
                if pattern['common_contexts']:
                    st.write(html_rtl(f"• {t('Preferred Context')}: {', '.join(pattern['common_contexts'])}"))
                if pattern['common_tags']:
                    st.write(html_rtl(f"• {t('Common Emotions')}: {', '.join(pattern['common_tags'])}"))
            else:
                st.markdown("### 🧠 Your Behavioral Pattern")
                st.write(f"• **{t('Common Symbols')}**: {', '.join(pattern['common_symbols'])}")
                st.write(f"• **{t('Preferred Side')}**: {pattern['common_side'].upper()}")
                st.write(f"• **{t('Common Type')}**: {pattern['common_type']}")
                st.write(f"• **{t('Avg Leverage')}**: {pattern['avg_leverage']:.1f}x")
                if pattern['common_contexts']:
                    st.write(f"• **{t('Preferred Context')}**: {', '.join(pattern['common_contexts'])}")
                if pattern['common_tags']:
                    st.write(f"• **{t('Common Emotions')}**: {', '.join(pattern['common_tags'])}")

        # --- تکامل رفتاری ---
        if evolution:
            if language == "فارسی":
                st.markdown(html_rtl("### 🚀 تکامل رفتاری"), unsafe_allow_html=True)
                st.write(html_rtl(f"• **{t('Improvement')}**: {evolution['improvement']:.0f}%"))
                st.write(html_rtl(f"• **{t('Early Avg R:R')}**: {evolution['early_avg_rr']:.2f}"))
                st.write(html_rtl(f"• **{t('Recent Avg R:R')}**: {evolution['recent_avg_rr']:.2f}"))
                if evolution['trend'] == "improving":
                    st.success(html_rtl("🎉 تبریک! داری به یک تریدر حرفه‌ای تبدیل می‌شی."))
                else:
                    st.info(html_rtl("همین روند رو ادامه بده، نتیجه میده."))
            else:
                st.markdown("### 🚀 Behavioral Evolution")
                st.write(f"• **{t('Improvement')}**: {evolution['improvement']:.0f}%")
                st.write(f"• **{t('Early Avg R:R')}**: {evolution['early_avg_rr']:.2f}")
                st.write(f"• **{t('Recent Avg R:R')}**: {evolution['recent_avg_rr']:.2f}")
                if evolution['trend'] == "improving":
                    st.success("🎉 Great progress! You're becoming a disciplined trader.")
                else:
                    st.info("Keep going! Consistency leads to results.")

        # --- تحلیل عملکرد بر اساس استراتژی ---
        if strategy_perf:
            st.markdown("### 📊 " + t("Performance by Strategy"))
            for perf in strategy_perf:
                with st.expander(f"📈 {perf['strategy_name']} ({perf['trade_count']} trades)"):
                    col1, col2, col3 = st.columns(3)
                    col1.metric(t("Total PnL"), f"{perf['total_pnl']}$")
                    col2.metric(t("Avg R:R"), perf['avg_rr'])
                    col3.metric(t("Win Rate"), f"{perf['win_rate']:.1%}")
                    
                    if perf['avg_rr'] > 1.0:
                        st.success("✅ High-quality strategy")
                    elif perf['avg_rr'] < 0.5:
                        st.warning("⚠️ Needs improvement")

        # --- تشخیص تغییر استراتژی ---
        if strategy_change and strategy_change['changed']:
            st.info(f"🔄 {t('You changed strategy')} from {strategy_change['from']} to {strategy_change['to']}")
            
            first_period = trades[-len(trades)//2:]
            last_period = trades[:len(trades)//2]
            first_pnl = sum(t['profit_or_loss'] for t in first_period)
            last_pnl = sum(t['profit_or_loss'] for t in last_period)
            
            if last_pnl > first_pnl:
                st.success(t("The new strategy is performing better!"))
            else:
                st.warning(t("The new strategy needs adjustment."))

        # --- معاملات اخیر ---
        if language == "فارسی":
            st.markdown(html_rtl("### 📜 معاملات اخیر"), unsafe_allow_html=True)
        else:
            st.write("### 📜 Recent Trades")
        for t in trades[:10]:
            tags = ", ".join(t['psychological_tags'])
            st.text(f"{t['symbol']} | {t['side'].upper()} | PnL: {t['profit_or_loss']}$ | R:R: {t['rr_calculated']:.2f} | [{tags}]")