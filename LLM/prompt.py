PROMPT_ALL = """
You are an expert software testing engineer.
Your task is to generate the test oracle (assertion) for a unit test.
Requirements:
1. Analyze the function documentation.
2. Analyze the function implementation.
3. Analyze the test prefix.
4. Infer the expected output.
5. Do NOT output explanations.
6. Do NOT repeat the test prefix.

Function Documentation:
{function_doc}

Function Code:
{function_code}

Function Signature:
{function_sig}

Test Signature:
{test_sig}

Test Prefix:
{prefix}

Output:
"""

PROMPT_NO_DOC = """
You are an expert software testing engineer.
Your task is to generate the test oracle (assertion) for a unit test.
Requirements:
1. Analyze the function implementation.
2. Analyze the test prefix.
3. Infer the expected output.
4. Do NOT output explanations.
5. Do NOT repeat the test prefix.

Function Code:
{function_code}

Function Signature:
{function_sig}

Test Signature:
{test_sig}

Test Prefix:
{prefix}

Output:
"""

PROMPT_NO_INLINE = """
You are an expert software testing engineer.
Your task is to generate the test oracle (assertion) for a unit test.
Requirements:
1. Analyze the function documentation.
2. Analyze the function implementation.
3. Analyze the test prefix.
4. Infer the expected output.
5. Do NOT output explanations.
6. Do NOT repeat the test prefix.

Function Documentation:
{function_doc}

Function Code:
{function_pure_code}

Function Signature:
{function_sig}

Test Signature:
{test_sig}

Test Prefix:
{prefix}

Output:
"""

PROMPT_NO_DOC_INLINE = """
You are an expert software testing engineer.
Your task is to generate the test oracle (assertion) for a unit test.
Requirements:
1. Analyze the function implementation.
2. Analyze the test prefix.
3. Infer the expected output.
4. Do NOT output explanations.
5. Do NOT repeat the test prefix.

Function Code:
{function_pure_code}

Function Signature:
{function_sig}

Test Signature:
{test_sig}

Test Prefix:
{prefix}

Output:
"""

PROMPT_NO_CODE = """
You are an expert software testing engineer.
Your task is to generate the test oracle (assertion) for a unit test.
Requirements:
1. Analyze the function documentation.
2. Analyze the function signature.
3. Analyze the test prefix.
4. Infer the expected output.
5. Do NOT output explanations.
6. Do NOT repeat the test prefix.

Function Documentation:
{function_doc}

Function Signature:
{function_sig}

Test Signature:
{test_sig}

Test Prefix:
{prefix}

Output:
"""

PROMPT_ONLY_SIG = """
You are an expert software testing engineer.
Your task is to generate the test oracle (assertion) for a unit test.
Requirements:
1. Analyze the function signature.
2. Analyze the test prefix.
3. Infer the expected output.
4. Do NOT output explanations.
5. Do NOT repeat the test prefix.

Function Signature:
{function_sig}

Test Signature:
{test_sig}

Test Prefix:
{prefix}

Output:
"""
