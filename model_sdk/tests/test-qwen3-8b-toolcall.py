from openai import OpenAI
import json

openai_api_key = "EMPTY"
openai_api_base = "http://10.xxx.xxx.xxx:xxx/v1"

client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

model_name = "qwen3-8b"


def get_current_temperature(location: str, unit: str = "celsius"):
    """Get current temperature at a location.

    Args:
        location: The location to get the temperature for, in the format "City, State, Country".
        unit: The unit to return the temperature in. Defaults to "celsius". (choices: ["celsius", "fahrenheit"])

    Returns:
        the temperature, the location, and the unit in a dict
    """
    return {
        "temperature": 26.1,
        "location": location,
        "unit": unit,
    }


def get_temperature_date(location: str, date: str, unit: str = "celsius"):
    """Get temperature at a location and date.

    Args:
        location: The location to get the temperature for, in the format "City, State, Country".
        date: The date to get the temperature for, in the format "Year-Month-Day".
        unit: The unit to return the temperature in. Defaults to "celsius". (choices: ["celsius", "fahrenheit"])

    Returns:
        the temperature, the location, the date and the unit in a dict
    """
    return {
        "temperature": 25.9,
        "location": location,
        "date": date,
        "unit": unit,
    }


def get_function_by_name(name):
    if name == "get_current_temperature":
        return get_current_temperature
    if name == "get_temperature_date":
        return get_temperature_date


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_temperature",
            "description": "Get current temperature at a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": 'The location to get the temperature for, in the format "City, State, Country".',
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": 'The unit to return the temperature in. Defaults to "celsius".',
                    },
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_temperature_date",
            "description": "Get temperature at a location and date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": 'The location to get the temperature for, in the format "City, State, Country".',
                    },
                    "date": {
                        "type": "string",
                        "description": 'The date to get the temperature for, in the format "Year-Month-Day".',
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": 'The unit to return the temperature in. Defaults to "celsius".',
                    },
                },
                "required": ["location", "date"],
            },
        },
    },
]


MESSAGES = [
    {"role": "user",  "content": "What's the temperature in San Francisco now? How about tomorrow? Current Date: 2024-09-30."},
]


tools = TOOLS
messages = MESSAGES

response = client.chat.completions.create(
    model=model_name,
    messages=messages,
    tools=tools,
    temperature=0.7,
    top_p=0.8,
    max_tokens=1512,
    extra_body={
        "repetition_penalty": 1.05,
        "chat_template_kwargs": {"enable_thinking": False}  # default to True
    },
)


# print(response)


# output

# ChatCompletion(
# id='chatcmpl-78c47955e2ae40358383a01845c59109', 
# choices=[
#   Choice(
#       finish_reason='tool_calls', 
#       index=0, 
#       logprobs=None, 
#       message=
#           ChatCompletionMessage(
#               content=None, 
#               refusal=None, 
#               role='assistant', 
#               annotations=None, 
#               audio=None, 
#               function_call=None, 
#               tool_calls=[
#                   ChatCompletionMessageToolCall(
#                       id='chatcmpl-tool-fb29aa3d9759449ba8c52f8c2909eab6', 
#                       function=
#                           Function(
#                               arguments='{"location": "San Francisco, California, USA"}', name='get_current_temperature'), type='function'), 
#                   ChatCompletionMessageToolCall(
#                       id='chatcmpl-tool-68c31220421f45fbb406e6294ee230f8', 
#                       function=
#                           Function(arguments='{"location": "San Francisco, California, USA", "date": "2024-10-01"}', name='get_temperature_date'), type='function')
#               ], 
#               reasoning_content=None
#           ), 
#           stop_reason=None
#     )
#   ], 
#   created=1752738818, 
#   model='qwen3-8b', 
#   object='chat.completion', 
#   service_tier=None, 
#   system_fingerprint=None, 
#   usage=CompletionUsage(completion_tokens=67, prompt_tokens=400, total_tokens=467, completion_tokens_details=None, prompt_tokens_details=None), 
#   prompt_logprobs=None
# )


messages.append(response.choices[0].message.model_dump())

if tool_calls := messages[-1].get("tool_calls", None):
    for tool_call in tool_calls:
        call_id: str = tool_call["id"]
        if fn_call := tool_call.get("function"):
            fn_name: str = fn_call["name"]
            fn_args: dict = json.loads(fn_call["arguments"])
        
            fn_res: str = json.dumps(get_function_by_name(fn_name)(**fn_args))

            messages.append({
                "role": "tool",
                "content": fn_res,
                "tool_call_id": call_id,
            })

#  The messages are now like

# [
#     {'role': 'user', 'content': "What's the temperature in San Francisco now? How about tomorrow? Current Date: 2024-09-30."},
#     {'content': None, 'role': 'assistant', 'function_call': None, 'tool_calls': [
#         {'id': 'chatcmpl-tool-924d705adb044ff88e0ef3afdd155f15', 'function': {'arguments': '{"location": "San Francisco, CA, USA"}', 'name': 'get_current_temperature'}, 'type': 'function'},
#         {'id': 'chatcmpl-tool-7e30313081944b11b6e5ebfd02e8e501', 'function': {'arguments': '{"location": "San Francisco, CA, USA", "date": "2024-10-01"}', 'name': 'get_temperature_date'}, 'type': 'function'},
#     ]},
#     {'role': 'tool', 'content': '{"temperature": 26.1, "location": "San Francisco, CA, USA", "unit": "celsius"}', 'tool_call_id': 'chatcmpl-tool-924d705adb044ff88e0ef3afdd155f15'},
#     {'role': 'tool', 'content': '{"temperature": 25.9, "location": "San Francisco, CA, USA", "date": "2024-10-01", "unit": "celsius"}', 'tool_call_id': 'chatcmpl-tool-7e30313081944b11b6e5ebfd02e8e501'},
# ]

response = client.chat.completions.create(
    model=model_name,
    messages=messages,
    tools=tools,
    temperature=0.7,
    top_p=0.8,
    max_tokens=512,
    extra_body={
        "repetition_penalty": 1.05,
        "chat_template_kwargs": {"enable_thinking": False}  # default to True
    },
)

messages.append(response.choices[0].message.model_dump())


print(response.choices[0].message.content)


# output

# enable_thinking: false

# The current temperature in San Francisco, California, USA is 26.1°C. 

# Tomorrow, on 2024-10-01, the temperature is expected to be 25.9°C.



# enable_thinking: true

# <think>
# Okay, let me process this. The user asked for the current temperature in San Francisco and tomorrow's. The assistant called both functions correctly. The responses came back in Celsius. The current temp is 26.1°C, and tomorrow it's 25.9°C. I should present these clearly, maybe mention the dates again for clarity. Also, offer to convert to Fahrenheit if needed. Keep it friendly and straightforward.
# </think>

# The current temperature in San Francisco, California, USA is **26.1°C**. 

# Tomorrow (2024-10-01), the temperature is expected to be **25.9°C**. 

# Would you like the temperatures in Fahrenheit as well?



