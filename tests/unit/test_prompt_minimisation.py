"""E3.4 DPDP minimisation: contact details never reach an LLM prompt; order facts still do."""

import pytest

from app.agents.prompts import classifier_messages, fence_customer, mask_contact_details


@pytest.mark.parametrize(
    "text",
    [
        "call me on 9876543210",
        "my number is +91 98765 43210",
        "reach me at 098765-43210",
        "email me: priya.s+food@example.co.in",
    ],
)
def test_contact_details_are_masked(text):
    masked = mask_contact_details(text)
    assert "[phone]" in masked or "[email]" in masked
    assert "@" not in masked and "98765" not in masked and "9876543210" not in masked


def test_order_facts_in_the_message_are_kept():
    text = "Order O0005952 came 89 minutes late, I paid Rs 528 on 30/09"
    assert mask_contact_details(text) == text


def test_every_prompt_gets_the_masked_message():
    msgs = classifier_messages("late again, call 9876543210", ["late_delivery"], {})
    body = msgs[1].content
    assert "9876543210" not in body and "[phone]" in body
    assert "9876543210" not in fence_customer("9876543210")
