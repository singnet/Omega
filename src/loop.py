import datetime
import inspect
import json
import os
import sys
import openai
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]                                            # .../OmegaClaw-Core
_PETTA_PATH = Path(os.environ.get("PETTA_PATH", str(Path(__file__).resolve().parents[3])))  # .../PeTTa
sys.path.insert(0, str(_PETTA_PATH / "python"))
sys.path.insert(0, str(_REPO_ROOT))  # so "from src.logger import ..." etc. resolve
import petta
import time

# --------------------------------------------------------------------
# 0. Configuration:
# --------------------------------------------------------------------
MAX_TOOL_CALLS = 10
PRINT_CALLS = False
MAX_TOOL_OUTPUT_CHARS = 5000
EPISODIC_TRACE_SIZE = 100
MAX_FAST_STEPS = 50
SLOW_STEP_DELAY = 10
ERROR_RECOVERY_TIME = 1 #after how long to retry when exception occurs
RETURN_VALUE_PRESERVE = 0
DEFAULT_DELAY = 0 #default delay added irregard of whether in slow mode
MAX_TOKENS = 1000
INIT_WAIT = 10
MODEL = os.getenv("LLM_MODEL", "mlx-community/gemma-4-26b-a4b-it-4bit")
BASE_URL = os.getenv("BASE_URL", "http://192.168.64.1:2277/v1")
API_KEY = os.getenv("AI_API_KEY", "dummy")
PROMPT = open(str(_REPO_ROOT / "memory" / "prompt.txt")).read().strip()

# --------------------------------------------------------------------
# 1. MeTTa init:
# --------------------------------------------------------------------
# chdir to _PETTA_PATH so relative paths used by git-import! and library
# resolution (./repos/OmegaClaw-Core etc.) resolve the same as running from ~/PeTTa.
os.chdir(str(_PETTA_PATH))
MeTTa = petta.PeTTa()
# load_metta_file sets the MeTTa working_dir to the file's directory, which is
# required for (library OmegaClaw-Core ...) to resolve repos/OmegaClaw-Core.
# process_metta_string does not set working_dir, so we write a temp load file
# in _PETTA_PATH and load_metta_file it instead.
# git-import! asserts library_path/1 so (library OmegaClaw-Core ...) can resolve.
_load_path = _PETTA_PATH / "_omegaclaw_load.metta"
_load_path.write_text(
    "!(import! &self (library lib_import))\n"
    '!(git-import! "https://github.com/asi-alliance/OmegaClaw-Core.git")\n'
    "!(import! &self (library OmegaClaw-Core lib_omegaclaw))\n"
)
MeTTa.load_metta_file(str(_load_path))
_load_path.unlink(missing_ok=True)
print(MeTTa.process_metta_string("!(initConfig)"))
print(MeTTa.process_metta_string("!(initLoop)"))
print(MeTTa.process_metta_string("!(initMemory)"))
print(MeTTa.process_metta_string("!(initPlugins)"))
print(MeTTa.process_metta_string("!(initChannels)"))

# --------------------------------------------------------------------
# 2. Local tool helpers:
# --------------------------------------------------------------------
def metta_string_escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

def get_current_time():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def run_metta(command, *args):
    arguments = " ".join(f'"{metta_string_escape(arg)}"' for arg in args)
    expression = f"!({command}{' ' + arguments if arguments else ''})"
    if PRINT_CALLS and command != "send":
        argl = " ".join(map(str, args))
        component = "(" + command + " " + argl + ")"
        component = component.replace('"',"_quote_").replace("'","_apostrophe_")
        command = f"!(send \"{component}\")"
        MeTTa.process_metta_string(command)
    return str(MeTTa.process_metta_string(expression))

def metta(sexpression):
    ret = MeTTa.process_metta_string(f'!(metta "{metta_string_escape(sexpression)}")')
    #MeTTa.process_metta_string("!(bound-space! &persistent (maxPersistentAtomsChars))")
    #MeTTa.process_metta_string("!(export! &persistent ./repos/mettaclaw/memory/persistent.metta)")
    if PRINT_CALLS:
        component = sexpression.replace('"',"_quote_").replace("'","_apostrophe_")
        command = f"!(send \"{component}\")"
        MeTTa.process_metta_string(command)
    return ret

def append_episode(content):
    with open(str(_REPO_ROOT / "memory" / "history.metta"), "a") as file:
        file.write("(\"" + get_current_time() + "\" " + content + ")\n")

def slow_wait_for_input():
    for second in range(SLOW_STEP_DELAY):
        time.sleep(1)
        event_append = str(MeTTa.process_metta_string("!(receive)")[0]).replace("(@ none)","")
        if event_append:
            return event_append
    return ""

# --------------------------------------------------------------------
# 3. Local tools:
# --------------------------------------------------------------------
INOPS = { "metta": (lambda sexpression: "SUCCESS, RETURN: " + str(metta(sexpression)), "Evaluate a MeTTa s-expression, since its a s-expression omit the ! in the beginning. Use (add-atom &persistent X) to add X to space, same for remove-atom."),
          "pin": (lambda message: "SUCCESS, RETURN: " + run_metta("pin", message), "Pin a string as a short-term working-memory item to keep track of task state and relevant query results as query returns are only available once and gone next cycle."),
          "episodes": (lambda timestamp: "SUCCESS, RETURN: " + run_metta("episodes", timestamp), "Search history for episodes around a timestamp in %Y-%m-%d %H:%M:%S format."),
          "update": (lambda timestamp_ltm, updated_content: "SUCCESS, RETURN: " + run_metta("update", timestamp_ltm, updated_content), "Update the label and embedding of a memory, linked episodes and promotion will transfer over, time format here with underline: %Y-%m-%d_%H:%M:%S"),  
          "link": (lambda timestamp_ltm, timestamp_episode: "SUCCESS, RETURN: " + run_metta("link", timestamp_ltm, timestamp_episode), "Link episode to LTM item, has no promotion effect, both times with %Y-%m-%d_%H:%M:%S format"),
          "unlink": (lambda timestamp_ltm, timestamp_episode: "SUCCESS, RETURN: " + run_metta("unlink", timestamp_ltm, timestamp_episode), "Unlink episode from LTM, both times with %Y-%m-%d_%H:%M:%S format"),
          "support": (lambda timestamp_ltm, timestamp_episode: "SUCCESS, RETURN: " + run_metta("support", timestamp_ltm, timestamp_episode), "When an episode supports LTM item, linking it to the episode time, and positively updating its truth value, bot times in %Y-%m-%d_%H:%M:%S format"),
          "contradict": (lambda timestamp_ltm, timestamp_episode: "SUCCESS, RETURN: " + run_metta("contradict", timestamp_ltm, timestamp_episode), "When an episode contradicts LTM item, linking it to the episode time, and negatively updating its truth value, both times in %Y-%m-%d_%H:%M:%S format"),
          "query": (lambda content: "SUCCESS, RETURN: " + run_metta("query", content), "Query long-term embedding memory using a short phrase."),
          "remember": (lambda content: "SUCCESS, RETURN: " + run_metta("remember", content), "Remember a particular string such as a skill or memory."),
          "forget": (lambda timestamp_ltm: "SUCCESS, RETURN: " + run_metta("forget", timestamp_ltm), "Forget a particular LTM item via its timestamp, arg format: %Y-%m-%d %H:%M:%S"),
          "send": (lambda content: "SUCCESS, RETURN: " + run_metta("send", content), "To send a message to the user but keep yourself very brief."),
          "nop": (lambda: print("NOP") or "SUCCESS", "Perform no action if task is complete, do not re-send!"),
          "websearch": (lambda content: "SUCCESS, RETURN: " + run_metta("websearch", content), "Search the internet for content."),
          "read-file": (lambda filename: "SUCCESS, RETURN: " + run_metta("read-file", filename), "Read a file."),
          "write-file": (lambda filename, content: "SUCCESS, RETURN: " + run_metta("write-file", filename, content), "Write content to a file, replacing its previous contents."),
          "append-file": (lambda filename, content: "SUCCESS, RETURN: " + run_metta("append-file", filename, content), "Append content to a file."),
          "shell": (lambda cmd: "SUCCESS, RETURN: " + run_metta("shell", cmd), "Execute a shell command.") }

def native_tools(inops):
    tools = []
    for name, (fn, description) in inops.items():
        parameters = inspect.signature(fn).parameters.values()
        tools.append({"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": { parameter.name: { "type": "string" } for parameter in parameters }, "required": [parameter.name for parameter in parameters], "additionalProperties": False}}})
    return tools

# --------------------------------------------------------------------
# 4. Main loop
# --------------------------------------------------------------------
TOOLS = native_tools(INOPS)
selfprompt = [{"role": "system", "content": PROMPT}]
messages_all = []
client = openai.OpenAI(api_key=API_KEY, base_url=BASE_URL)
time.sleep(INIT_WAIT)
post_task_mode, autonomous_steps, new_burst, pending_event_append = False, 0, True, ""
while True:
    history_checkpoint = len(messages_all)
    try:
        time.sleep(DEFAULT_DELAY)
        event_append = pending_event_append or str(MeTTa.process_metta_string("!(receive)")[0]).replace("(@ none)","")
        pending_event_append = ""
        temporary_message = []
        if event_append:
            autonomous_steps, new_burst, post_task_mode = 0, False, False
            print("IN FROM CHANNEL " + event_append)
            messages_all += [{"role": "user", "content": "Step " + get_current_time() + ": " + event_append}]
            append_episode("HUMAN_MESSAGE: " + messages_all[-1]["content"])
        elif new_burst:
            post_task_mode, new_burst = True, False
            temporary_message += [{"role": "user", "content": "Step " + get_current_time() + ": [TASK COMPLETED. DO NOT RE-SEND THE COMPLETED RESPONSE. NOW QUERY FOR AND PICK A TASK BASED ON YOUR GOALS, PREFERABLY MEMORY CONSOLIDATION: FINDING EPISODES WHICH SUPPORT / CONTRADICT LTM ITEMS, LINKING EPISODES, PROMOTING USEFUL MEMORIES]"}]
        elif post_task_mode:
            temporary_message += [{"role": "user", "content": "Step " + get_current_time() + ": [NO NEW USER INPUT. CONTINUE AUTONOMOUS WORK. DO NOT REPEAT THE PREVIOUS RESPONSE. ONLY USE send FOR GENUINELY NEW INFORMATION OR WHEN USER INPUT IS NEEDED.]"}]
        else:
            temporary_message += [{"role": "user", "content": "Step " + get_current_time() + ": [NO ADDITIONAL USER INPUT. CONTINUE THE CURRENT USER TASK.]"}]
        recent_messages = messages_all[-EPISODIC_TRACE_SIZE:]
        while recent_messages and recent_messages[0].get("role") == "tool":
            recent_messages = recent_messages[1:]
        while True:
            response = client.chat.completions.create(model=MODEL, messages=selfprompt + recent_messages + temporary_message, tools=TOOLS, tool_choice="required", max_tokens=MAX_TOKENS)
            message = response.choices[0].message
            if message.tool_calls:
                message.tool_calls = message.tool_calls[:MAX_TOOL_CALLS]
                break
            temporary_message += [{"role": "user", "content": "Your previous response was invalid. Do not answer in plain text. Call at least one tool now."}]
        print(f"RESPONSE {response}\nFINISH_REASON {response.choices[0].finish_reason}\nUSAGE {response.usage}")
        messages_all = [{**old_message, "content": old_message.get("content", "")[:RETURN_VALUE_PRESERVE] + " ... omitted"} if old_message.get("role") == "tool" and " ... omitted" not in old_message.get("content", "") else old_message for old_message in messages_all]
        messages_all += [{**{key: value for key, value in message.model_dump(exclude_none=True).items() if key not in ("reasoning", "reasoning_details", "reasoning_content")}, "content": "Step " + get_current_time() + ": [TOOL CALL]"}]
        tool_outputs = []
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as error:
                tool_arguments = tool_call.function.arguments
                ret = f"Invalid tool arguments from model: {error}"
            else:
                try:#unless tool unknown/args formatting issue, we use the tool's INOPS function return value:
                    ret = f"Unknown tool: {tool_name!r}" if tool_name not in INOPS else "Tool arguments must be a JSON object" if not isinstance(tool_arguments, dict) else INOPS[tool_name][0](**tool_arguments)
                except Exception as error:
                    ret = f"Tool execution failed: {type(error).__name__}: {error}"
            ret = str(ret)[:MAX_TOOL_OUTPUT_CHARS]
            messages_all += [{"role": "tool", "tool_call_id": tool_call.id, "content": "Step " + get_current_time() + ": " + ret}]
            append_episode(f"({tool_name} {tool_arguments})")
            tool_outputs += ["tool call: " + tool_name + " " + str(tool_arguments) + "\n" "tool return: " + ret]
        with open("messages_all.json", "w", encoding="utf-8") as file:
            json.dump(messages_all, file, ensure_ascii=False, indent=2)
        print("Output> " + "\n".join(tool_outputs))
        autonomous_steps = 0 if event_append else autonomous_steps + 1
        if tool_name == "nop" or autonomous_steps >= MAX_FAST_STEPS:
            new_burst, autonomous_steps = True, 0
            pending_event_append = slow_wait_for_input()
    except Exception as error:
        print(f"Output> {type(error).__name__}: {error}")
        messages_all = messages_all[:history_checkpoint]
        time.sleep(ERROR_RECOVERY_TIME)
