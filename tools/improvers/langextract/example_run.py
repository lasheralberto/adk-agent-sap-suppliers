"""Small example runner for the LangExtractProvider.

This demonstrates how to call the provider with explicit `model_id` and `api_key`.
"""
from tools.improvers.langextract import LangExtractProvider


def main():
    provider = LangExtractProvider(model_id="gpt-4o-mini", api_key="REPLACE_WITH_KEY")
    text = "Google acquired DeepMind in 2014, strengthening its position in artificial intelligence research."
    result = provider.extract(text)
    print("Extraction result:")
    print(result)


if __name__ == "__main__":
    main()
