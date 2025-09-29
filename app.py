import asyncio
import json
import requests
import streamlit as st
from openai import OpenAI
from datetime import datetime

# ----------------------------
# Calculator Tool
# ----------------------------
async def calculator(expression: str) -> str:
    try:
        result = eval(expression, {"__builtins__": {}})
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

# ----------------------------
# Weather Tool
# ----------------------------
def get_weather(city: str, api_key: str) -> str:
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
        resp = requests.get(url)
        data = resp.json()
        if resp.status_code == 401:
            return "INVALID_API_KEY"
        if resp.status_code != 200:
            return f"⚠️ Error: {data.get('message', 'Failed to fetch weather')}"
        temp = data["main"]["temp"]
        desc = data["weather"][0]["description"]
        return f"🌦️ Weather in {city}: {temp}°C, {desc}"
    except Exception as e:
        return f"⚠️ Error fetching weather: {e}"

# ----------------------------
# News Tool
# ----------------------------
def get_news(query: str, api_key: str) -> str:
    try:
        url = f"https://newsapi.org/v2/everything?q={query}&apiKey={api_key}&pageSize=3"
        resp = requests.get(url)
        data = resp.json()
        if resp.status_code == 401:
            return "INVALID_API_KEY"
        if resp.status_code != 200:
            return f"⚠️ Error: {data.get('message', 'Failed to fetch news')}"
        articles = data.get("articles", [])
        if not articles:
            return f"📰 No news found for '{query}'."
        headlines = "\n".join([f"- {a['title']} ({a['source']['name']})" for a in articles[:3]])
        return f"📰 Top news for '{query}':\n{headlines}"
    except Exception as e:
        return f"⚠️ Error fetching news: {e}"

# ----------------------------
# Streamlit Setup
# ----------------------------
st.set_page_config(page_title="Smart Chatbot", page_icon="🤖", layout="wide")
st.title("🤖 Human-in-the-Loop Chatbot with Threads & Summaries")

# Sidebar API Keys
st.sidebar.header("🔑 API Keys")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password")
weather_key = st.sidebar.text_input("OpenWeather API Key", type="password")
news_key = st.sidebar.text_input("NewsAPI Key", type="password")

if not openai_key:
    st.warning("Please provide your OpenAI API key in the sidebar.")
    st.stop()

client = OpenAI(api_key=openai_key)

# ----------------------------
# Threads Setup
# ----------------------------
if "threads" not in st.session_state:
    st.session_state.threads = {}

if "current_thread" not in st.session_state:
    st.session_state.current_thread = None

# Sidebar: Select or Create Thread
st.sidebar.subheader("🧵 Threads")
existing_threads = list(st.session_state.threads.keys())
if existing_threads:
    selected_thread = st.sidebar.selectbox("Select a thread", existing_threads, index=0)
else:
    selected_thread = None

new_thread_btn = st.sidebar.button("➕ New Thread")
if new_thread_btn:
    thread_id = f"thread-{len(st.session_state.threads)+1}"
    st.session_state.threads[thread_id] = {
        "messages": [],
        "tool_counts": {"calculator": 0, "weather": 0, "news": 0},
        "tokens_used": 0,
        "pending_tool": None,
        "start_time": datetime.now(),
    }
    st.session_state.current_thread = thread_id
elif selected_thread:
    st.session_state.current_thread = selected_thread

if not st.session_state.current_thread:
    st.info("👉 Create or select a thread from sidebar")
    st.stop()

thread = st.session_state.threads[st.session_state.current_thread]
messages = thread["messages"]

# ----------------------------
# Router: Ask LLM
# ----------------------------
def classify_and_extract(user_msg: str):
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": """You are a tool router. 
If the user asks a math question, respond ONLY with JSON:
{"tool": "calculator", "arguments": {"expression": "<math expression>"}}

If it's about weather:
{"tool": "weather", "arguments": {"city": "<city name>"}}

If it's about news:
{"tool": "news", "arguments": {"topic": "<topic>"}}

Otherwise:
{"tool": "general", "arguments": {}}"""},
            {"role": "user", "content": user_msg},
        ]
    )
    thread["tokens_used"] += resp.usage.total_tokens
    try:
        return json.loads(resp.choices[0].message.content)
    except:
        return {"tool": "general", "arguments": {}}

# ----------------------------
# Chat Input
# ----------------------------
user_msg = st.chat_input("Type your message...")
if user_msg:
    messages.append({"role": "user", "content": user_msg})
    route = classify_and_extract(user_msg)
    tool = route["tool"]
    args = route["arguments"]

    if tool in ["calculator", "weather", "news"]:
        thread["pending_tool"] = {"tool": tool, "args": args}
        messages.append({
            "role": "assistant",
            "content": f"🤔 I think I should use **{tool}** with `{args}`.\n\nDo you approve?",
            "pending": True
        })
    else:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "You are a helpful chatbot."}] + messages
        )
        reply = resp.choices[0].message.content
        thread["tokens_used"] += resp.usage.total_tokens
        messages.append({"role": "assistant", "content": reply})

# ----------------------------
# Display Chat with Approvals Inline
# ----------------------------
for i, msg in enumerate(messages):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg.get("pending") and thread["pending_tool"]:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Approve", key=f"approve_{i}"):
                    tool = thread["pending_tool"]["tool"]
                    args = thread["pending_tool"]["args"]

                    if tool == "calculator":
                        result = asyncio.run(calculator(args.get("expression", "")))
                    elif tool == "weather":
                        if not weather_key:
                            result = "⚠️ Provide your Weather API key in sidebar."
                        else:
                            result = get_weather(args.get("city", ""), weather_key)
                    elif tool == "news":
                        if not news_key:
                            result = "⚠️ Provide your NewsAPI key in sidebar."
                        else:
                            result = get_news(args.get("topic", ""), news_key)
                    else:
                        result = "⚠️ Unknown tool."

                    thread["tool_counts"][tool] += 1
                    messages.append({"role": "assistant", "content": result})
                    thread["pending_tool"] = None
                    st.rerun()

            with col2:
                if st.button("❌ Deny", key=f"deny_{i}"):
                    messages.append({"role": "assistant", "content": "❌ Tool request denied."})
                    thread["pending_tool"] = None
                    st.rerun()

# ----------------------------
# Session Summary (Metadata + Content Summary)
# ----------------------------
st.sidebar.subheader("📥 Session Summary")
if st.sidebar.button("Generate Summary"):
    duration = datetime.now() - thread["start_time"]

    # ✅ Ask LLM to summarize conversation content
    conv_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages if m["role"] in ["user","assistant"]])
    summary_resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Summarize the conversation in 3–5 sentences. Keep it concise and clear."},
            {"role": "user", "content": conv_text}
        ]
    )
    thread["tokens_used"] += summary_resp.usage.total_tokens
    conv_summary = summary_resp.choices[0].message.content.strip()

    # ✅ Build full summary text
    summary = f"🧵 Session Summary - {st.session_state.current_thread}\n"
    summary += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    summary += f"Duration: {str(duration).split('.')[0]}\n"
    summary += f"Messages: {len(messages)}\n\n"

    summary += f"📌 Conversation Summary:\n{conv_summary}\n\n"

    summary += "📊 Tool Usage:\n"
    for tool, count in thread["tool_counts"].items():
        summary += f"- {tool}: {count} times\n"

    summary += f"\n💎 Tokens Used: {thread['tokens_used']}\n"

    st.sidebar.download_button(
        label="⬇️ Download Summary",
        data=summary,
        file_name=f"{st.session_state.current_thread}_summary.txt",
        mime="text/plain",
    )
