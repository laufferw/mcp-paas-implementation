#!/usr/bin/env python3
"""
Sample model configurations for testing and development
"""

SAMPLE_MODELS = [
    {
        "name": "gpt-4",
        "version": "0402",
        "provider": "openai",
        "type": "llm",
        "description": "OpenAI's GPT-4 large language model",
        "default_parameters": {
            "temperature": 0.7,
            "max_tokens": 1024,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "stop": None,
            "seed": None,
        },
        "resource_requirements": {
            "cpu": 2,
            "memory": "8Gi",
            "gpu": {
                "type": "nvidia-a100",
                "count": 1,
                "memory": "40Gi"
            },
            "token_window_size": 8192,
            "cost_per_token": {
                "input": 0.00001,
                "output": 0.00003
            }
        },
        "metadata": {
            "supported_features": ["function_calling", "vision", "json_mode"],
            "benchmark_scores": {
                "mmlu": 0.86,
                "humaneval": 0.83
            },
            "recommended_use_cases": [
                "complex reasoning",
                "content generation",
                "creative writing",
                "research assistance"
            ]
        }
    },
    {
        "name": "gpt-3.5-turbo",
        "version": "0125",
        "provider": "openai",
        "type": "llm",
        "description": "OpenAI's GPT-3.5 Turbo large language model",
        "default_parameters": {
            "temperature": 0.9,
            "max_tokens": 2048,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "stop": None,
            "seed": None,
        },
        "resource_requirements": {
            "cpu": 1,
            "memory": "4Gi",
            "gpu": {
                "type": "nvidia-t4",
                "count": 1,
                "memory": "16Gi"
            },
            "token_window_size": 4096,
            "cost_per_token": {
                "input": 0.0000015,
                "output": 0.000002
            }
        },
        "metadata": {
            "supported_features": ["function_calling", "json_mode"],
            "benchmark_scores": {
                "mmlu": 0.70,
                "humaneval": 0.72
            },
            "recommended_use_cases": [
                "general conversation",
                "content summarization",
                "data extraction",
                "customer support"
            ]
        }
    },
    {
        "name": "claude-3-opus",
        "version": "20240229",
        "provider": "anthropic",
        "type": "llm",
        "description": "Anthropic's Claude 3 Opus large language model",
        "default_parameters": {
            "temperature": 0.5,
            "max_tokens": 4096,
            "top_p": 0.9,
            "top_k": 50,
            "stop_sequences": [],
        },
        "resource_requirements": {
            "cpu": 4,
            "memory": "16Gi",
            "gpu": {
                "type": "nvidia-a100",
                "count": 2,
                "memory": "80Gi"
            },
            "token_window_size": 200000,
            "cost_per_token": {
                "input": 0.000015,
                "output": 0.000075
            }
        },
        "metadata": {
            "supported_features": ["vision", "xml_mode"],
            "benchmark_scores": {
                "mmlu": 0.89,
                "humaneval": 0.88
            },
            "recommended_use_cases": [
                "complex reasoning",
                "research assistance",
                "code generation",
                "creative writing"
            ]
        }
    },
    {
        "name": "llama-3",
        "version": "70b",
        "provider": "meta",
        "type": "llm",
        "description": "Meta's Llama 3 70B large language model",
        "default_parameters": {
            "temperature": 0.8,
            "max_tokens": 2048,
            "top_p": 0.95,
            "repetition_penalty": 1.1,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
        },
        "resource_requirements": {
            "cpu": 2,
            "memory": "8Gi",
            "gpu": {
                "type": "nvidia-a100",
                "count": 2,
                "memory": "80Gi"
            },
            "token_window_size": 8192,
            "cost_per_token": {
                "input": 0.0000025,
                "output": 0.0000025
            }
        },
        "metadata": {
            "supported_features": ["function_calling"],
            "benchmark_scores": {
                "mmlu": 0.79,
                "humaneval": 0.70
            },
            "recommended_use_cases": [
                "content generation",
                "knowledge retrieval",
                "general reasoning"
            ]
        }
    },
    {
        "name": "stable-diffusion-xl",
        "version": "1.0",
        "provider": "stability-ai",
        "type": "image",
        "description": "Stability AI's Stable Diffusion XL text-to-image model",
        "default_parameters": {
            "prompt": "",
            "negative_prompt": "",
            "width": 1024,
            "height": 1024,
            "guidance_scale": 7.5,
            "num_inference_steps": 50,
            "seed": None,
        },
        "resource_requirements": {
            "cpu": 4,
            "memory": "16Gi",
            "gpu": {
                "type": "nvidia-a100",
                "count": 1,
                "memory": "40Gi"
            },
            "cost_per_inference": 0.02
        },
        "metadata": {
            "supported_features": ["text_to_image", "image_to_image", "inpainting", "outpainting", "controlnet"],
            "benchmark_scores": {
                "clip_score": 0.86,
                "fid": 9.7,
                "aesthetic_score": 8.2
            },
            "recommended_use_cases": [
                "digital art creation",
                "concept visualization",
                "product design",
                "creative content generation"
            ],
            "resolution_capabilities": {
                "min_width": 512,
                "max_width": 2048,
                "min_height": 512,
                "max_height": 2048,
                "aspect_ratio_limits": [0.5, 2.0]
            },
            "fine_tuning_supported": True
        }
    },
    {
        "name": "dalle-3",
        "version": "1.0",
        "provider": "openai",
        "type": "image",
        "description": "OpenAI's DALL-E 3 text-to-image model",
        "default_parameters": {
            "prompt": "",
            "size": "1024x1024",
            "quality": "standard",
            "style": "vivid",
            "n": 1,
            "response_format": "url"
        },
        "resource_requirements": {
            "cpu": 2,
            "memory": "8Gi",
            "gpu": {
                "type": "nvidia-a100",
                "count": 1,
                "memory": "40Gi"
            },
            "cost_per_inference": 0.04
        },
        "metadata": {
            "supported_features": ["text_to_image"],
            "benchmark_scores": {
                "clip_score": 0.89,
                "fid": 8.5,
                "aesthetic_score": 8.6
            },
            "recommended_use_cases": [
                "photorealistic images",
                "marketing content",
                "design mockups",
                "artistic illustrations"
            ],
            "resolution_capabilities": {
                "supported_sizes": ["1024x1024", "1024x1792", "1792x1024"]
            },
            "fine_tuning_supported": False
        }
    }
]

if __name__ == "__main__":
    import json
    print(json.dumps(SAMPLE_MODELS, indent=2))
