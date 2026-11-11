"""Tool schema and LLM parameter validators.
Refactored from et-addons/ai/utils/tools_schema/validators.py.
"""
import re
from types import NoneType

from ..exceptions import ValidationError
from .param_schema_validator import ParamSchemaValidator


def validate_input(input_schema, required_parameters):
    if required_parameters is None or not isinstance(required_parameters, list):
        raise ValueError(
            "The required properties should be specified as a list. i.e. 'required': [<property1_name>, ...]."
        )
    if any(required_property not in input_schema for required_property in required_parameters):
        raise ValueError(
            "Some properties are required but their definition is missing in the schema"
        )


def validate_schema(schema):
    parameters = schema.get("properties")
    required_parameters = schema.get("required")
    validate_input(parameters, required_parameters)
    for param_name, param_definition in parameters.items():
        param_validator = ParamSchemaValidator(param_name, param_definition)
        param_validator._validate()


def validate_params_llm_values_with_schema(instance, schema, required_parameters):
    JSON_SCHEMA_TO_PYTHON_TYPE = {
        "string": str,
        "integer": int,
        "number": (float, int),
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": NoneType,
    }

    for required in required_parameters:
        if required not in instance:
            raise ValidationError(
                f"Could you please provide info about '{required}' as it is required to process your request"
            )

    instance.update({param: None for param in schema if param not in instance})

    for name, value in instance.items():
        if name not in schema:
            raise ValidationError(f"Missing definition for {name}")
        if name not in required_parameters and value is None:
            continue

        param_type = schema[name]["type"]
        if isinstance(param_type, list):
            # Support ["string", "null"] from OpenAI strict schema conversion
            non_null_types = [t for t in param_type if t != "null"]
            param_type = non_null_types[0] if non_null_types else "null"
            if value is None:
                continue

        if param_type not in JSON_SCHEMA_TO_PYTHON_TYPE or not isinstance(
            value, JSON_SCHEMA_TO_PYTHON_TYPE[param_type]
        ):
            raise ValidationError(
                f"The type of the parameter '{name}' is incorrect. It should be '{param_type}'."
            )

        expected_pattern = param_type == "string" and schema[name].get("pattern")
        if expected_pattern and not re.fullmatch(expected_pattern, value):
            raise ValidationError(
                f"The value '{value}' of the parameter '{name}' doesn't match the expected pattern '{expected_pattern}'."
            )

        if (enum := schema[name].get("enum")) and value not in enum:
            raise ValidationError(
                f"Wrong value {value}, should be in: {', '.join(map(str, enum))}"
            )

        max_length = param_type == "string" and schema[name].get("maxLength")
        if isinstance(value, str) and max_length and len(value) > max_length:
            instance[name] = value[:max_length] + "..."

        if param_type == "object":
            instance[name] = validate_params_llm_values_with_schema(
                value,
                schema[name].get("properties", {}),
                schema[name].get("required", []),
            )

        if param_type == "array":
            item_name = f"{name}'s item"
            for item_value in value:
                validate_params_llm_values_with_schema(
                    {item_name: item_value},
                    {item_name: schema[name]["items"]},
                    [item_name],
                )

    return instance

