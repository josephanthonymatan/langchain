import examples as examples
import pytest
from pydantic.types import conlist

from langchain import FewShotPromptTemplate
from langchain.chat_models import ChatOpenAI
from langchain.data_generation.base import SyntheticDataGenerator
from langchain.data_generation.openai import create_openai_data_generator, OPENAI_TEMPLATE
from langchain.data_generation.prompts import SYNTHETIC_FEW_SHOT_PREFIX, SYNTHETIC_FEW_SHOT_SUFFIX, DEFAULT_PROMPT
from pydantic import BaseModel


# Define the desired output schema for individual medical billing record
class MedicalBilling(BaseModel):
    patient_id: int
    patient_name: str
    diagnosis_code: str
    procedure_code: str
    total_charge: float
    insurance_claim_amount: float


examples = [
    {
        "example": """Patient ID: 123456, Patient Name: John Doe, Diagnosis Code: J20.9, Procedure Code: 99203, 
        Total Charge: $500, Insurance Claim Amount: $350"""
    },
    {
        "example": """Patient ID: 789012, Patient Name: Johnson Smith, Diagnosis Code: M54.5, Procedure Code: 99213, 
        Total Charge: $150, Insurance Claim Amount: $120"""
    },
    {
        "example": """Patient ID: 345678, Patient Name: Emily Stone, Diagnosis Code: E11.9, Procedure Code: 99214, 
        Total Charge: $300, Insurance Claim Amount: $250"""
    },
    {
        "example": """Patient ID: 901234, Patient Name: Robert Miles, Diagnosis Code: B07.9, Procedure Code: 99204, 
        Total Charge: $200, Insurance Claim Amount: $160"""
    },
    {
        "example": """Patient ID: 567890, Patient Name: Clara Jensen, Diagnosis Code: F41.9, Procedure Code: 99205, 
        Total Charge: $450, Insurance Claim Amount: $310"""
    },
    {
        "example": """Patient ID: 234567, Patient Name: Alan Turing, Diagnosis Code: G40.909, Procedure Code: 99215, 
        Total Charge: $220, Insurance Claim Amount: $180"""
    }
]

prompt_template = FewShotPromptTemplate(
    prefix=SYNTHETIC_FEW_SHOT_PREFIX,
    examples=examples,
    suffix=SYNTHETIC_FEW_SHOT_SUFFIX,
    input_variables=["subject", "extra"],
    example_prompt=OPENAI_TEMPLATE,
)


@pytest.fixture(scope="function")
def synthetic_data_generator():
    return create_openai_data_generator(
        output_schema=MedicalBilling,
        llm=ChatOpenAI(temperature=1),  # replace with your LLM instance
        prompt=prompt_template
    )


@pytest.mark.requires("openai")
def test_generate_synthetic(synthetic_data_generator: SyntheticDataGenerator):
    synthetic_results = synthetic_data_generator.generate(subject="medical_billing",
                                                          extra="make sure the names are different", runs=10)
    assert len(synthetic_results) == 10
    for row in synthetic_results:
        assert isinstance(row, MedicalBilling)
    print(synthetic_results)


@pytest.mark.requires("openai")
@pytest.mark.asyncio
async def test_agenerate_synthetic(synthetic_data_generator: SyntheticDataGenerator):
    synthetic_results = await synthetic_data_generator.agenerate(subject="medical_billing",
                                                                 extra="Each value is different than the one before it.",
                                                                 runs=10)
    assert len(synthetic_results) == 10
    for row in synthetic_results:
        assert isinstance(row, MedicalBilling)
    print(synthetic_results)
