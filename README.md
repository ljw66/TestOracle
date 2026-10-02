# TestOracle

This repository contains the implementation and experimental infrastructure for our empirical study on **LLM-based test oracle generation for real-world C programs**.

The study investigates how different sources of contextual information affect oracle generation, how the semantic relevance of function documentation influences generated oracles, and whether LLM-generated oracles can detect faults under mutation testing.

The repository provides the oracle-generation pipeline, prompt templates, semantic matching implementation, LLM-based fallback evaluation, mutation generation tools, and supporting analysis scripts.

## Repository Structure

```text
TestOracle/
├── GenOracle/
│   ├── GenOracle.py
│   └── main.py
│
├── LLM/
│   ├── model.py
│   └── prompt.py
│
├── oracle_fix/
│   ├── Compare.py
│   ├── validate_syntax_sample.py
│   └── OracleCompare/
│
├── OracleCompareLLM/
│   └── CompareWithLLM.py
│
├── Mutation/
│   └── mutation_tool.py
│
└── tool/
    ├── RemoveComment.py
    └── summary.py
```

The main components are:

- **`GenOracle/`**: generates test oracles with LLMs and coordinates the experimental pipeline.
- **`LLM/`**: contains model configuration and prompt templates for different context configurations.
- **`oracle_fix/`**: performs automatic semantic comparison between generated and developer-written oracles.
- **`OracleCompareLLM/`**: provides the LLM-based fallback for cases that cannot be reliably resolved by the automatic comparison.
- **`Mutation/`**: generates first-order mutants for the mutation-testing experiment.
- **`tool/`**: contains preprocessing and experimental-result aggregation utilities.

## Experimental Pipeline

The main experimental workflow is:

```text
C Function + Developer Test
            │
            ▼
     Context Construction
            │
            ▼
       LLM Generation
            │
            ▼
   Generated Test Oracle
            │
            ▼
 Automatic Semantic Matching
            │
      ┌─────┴─────┐
      │           │
 resolved      unresolved
      │           │
      │           ▼
      │      LLM-based Fallback
      │           │
      └─────┬─────┘
            ▼
     Matching Result
```

For mutation analysis, generated oracles that can be integrated into executable tests are further evaluated against first-order mutants.

## Context Configurations

The oracle-generation experiment considers six prompt configurations based on combinations of the following information:

- **Prefix**: statements in the test before the target oracle.
- **Sig**: function and test signatures.
- **Code**: implementation of the function under test.
- **Doc**: function-level documentation.
- **Comment**: inline or block comments inside the function implementation.

The prompt templates are available in:

```text
LLM/prompt.py
```

The experiment configuration is defined in:

```text
GenOracle/main.py
```

The six configuration labels currently used by the implementation are:

```text
all
no_doc
no_inline
no_doc_inline
no_code
only_sig
```

These configurations allow the contribution of implementation code, function documentation, and inline comments to be examined separately.

## Evaluated LLMs

The experimental infrastructure supports the four LLMs evaluated in the study:

- DeepSeek-V4-Flash
- Qwen3.6-Plus
- GLM-5.1
- kimi-2.6

Model configuration is located in:

```text
LLM/model.py
```

The implementation uses an OpenAI-compatible API interface.

Before running an experiment, configure the API endpoint, API key, and target model in `LLM/model.py`.

**Do not commit private API keys to the repository.**

## Input Format

Each function under test is represented as a JSON file. A simplified example is:

```json
{
  "function_doc": "Function-level documentation.",
  "function_code": "int foo(int x) { /* ... */ }",
  "function_pure_code": "int foo(int x) { ... }",
  "function_sig": "int foo(int x)",
  "tests": [
    {
      "test_sig": "void test_foo(void)",
      "prefix": "int result = foo(1);",
      "oracle": "TEST_ASSERT_EQUAL_INT(2, result);"
    }
  ]
}
```

Here, `function_pure_code` contains the implementation after removing comments. The utility for generating this representation is available in:

```text
tool/RemoveComment.py
```

## Oracle Generation

Oracle generation is implemented in:

```text
GenOracle/GenOracle.py
```

For each test instance, the selected contextual information is inserted into the corresponding prompt template and sent to the configured LLM.

The generated output is stored together with the developer-written reference oracle:

```json
{
  "function_sig": "...",
  "test_sig": "...",
  "prefix": "...",
  "reference_oracle": "...",
  "generated_oracle": "..."
}
```

The batch experimental workflow is implemented in:

```text
GenOracle/main.py
```

Before running it, configure:

```python
BASE_DIR
PROJECTS
GEN_TYPES
MODELS
```

according to the local experimental environment.

## Oracle Matching

Generated oracles may use different assertion APIs or syntactic forms from developer-written references. Therefore, the evaluation does not rely on exact string matching.

The comparison pipeline is implemented under:

```text
oracle_fix/
```

The evaluator classifies each generated oracle into one of four categories:

| Category | Description |
|---|---|
| **Exact Match** | Generated and reference oracles express the same complete behavior |
| **Ref. ⊂ Gen.** | The reference behavior is contained in the generated oracle |
| **Gen. ⊂ Ref.** | The generated oracle covers only part of the reference behavior |
| **Mismatch** | Neither oracle semantically contains the other |

Cases that cannot be reliably resolved by the automatic comparison are passed to the LLM-based fallback implemented in:

```text
OracleCompareLLM/CompareWithLLM.py
```

This design allows heterogeneous C assertion APIs and semantically equivalent expressions to be compared beyond surface syntax.

## Mutation Testing

Mutation generation is implemented in:

```text
Mutation/mutation_tool.py
```

The tool uses Tree-sitter to generate **first-order mutants** for C programs.

It currently implements the following mutation operators:

| Operator | Description |
|---|---|
| AOR | Arithmetic Operator Replacement |
| ROR | Relational Operator Replacement |
| LOR | Logical Operator Replacement |
| BOR | Bitwise Operator Replacement |
| SOR | Shift Operator Replacement |
| CRP | Constant Replacement |
| UOI | Unary Operator Insertion |
| UOD | Unary Operator Deletion |
| ASR | Assignment Operator Replacement |
| ICR | Increment/Decrement Replacement |
| CNO | Condition Negation |
| RVR | Return Value Replacement |
| SDL | Statement Deletion |

An example invocation is:

```bash
python Mutation/mutation_tool.py path/to/source.c
```

Specific operators can be selected with:

```bash
python Mutation/mutation_tool.py path/to/source.c \
    --operators AOR,ROR,CNO,RVR
```

The generated mutants and their metadata are stored in the specified output directory.

## Requirements

The implementation is written in Python. Python 3.10 or later is recommended.

The main dependencies include:

```bash
pip install openai
pip install tree-sitter tree-sitter-c
pip install pycparser z3-solver
```

Additional dependencies may be required depending on the experiment being reproduced.

## Data Availability

This repository provides the **algorithms, implementation code, prompt templates, oracle-comparison procedures, mutation tools, and supporting experimental scripts** used in the study.

The underlying dataset is constructed from non-public real-world C projects. These projects and their associated source code, documentation, and developer-written tests are subject to confidentiality and ownership restrictions. We therefore do not have permission to redistribute the original dataset.

Consequently, the private source projects themselves are **not included in this repository**.

The released artifacts are intended to make the experimental methodology and implementation transparent while respecting the restrictions associated with the original data.

## Reproducing the Experiments

A typical reproduction workflow is:

1. Prepare input JSON files using the format described above.
2. Configure the LLM endpoint and model in `LLM/model.py`.
3. Configure the projects and experimental settings in `GenOracle/main.py`.
4. Run the oracle-generation pipeline.
5. Use `oracle_fix/` and `OracleCompareLLM/` to evaluate generated oracles.
6. Use `tool/summary.py` to aggregate experimental results.
7. For mutation analysis, generate mutants with `Mutation/mutation_tool.py` and execute the corresponding tests against the original program and its mutants.

Because the original experimental projects cannot be redistributed, reproducing the complete numerical results requires access to the corresponding private projects. The released code can nevertheless be applied to other C projects following the same input format.

## Citation

If you use this repository or the associated experimental methodology in your research, please cite the accompanying paper.

The citation information will be updated after publication.

## Contact

For questions about the artifact or experimental implementation, please open an issue in this repository.
