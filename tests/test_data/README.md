# Test Data

This directory stores recorded WWVB audio/IQ data for offline testing.

## Generating synthetic test data

Run the test data generator to create synthetic WWVB audio:

```bash
python -m tests.generate_test_data
```

This creates PCM audio files encoding known WWVB time frames that can be
replayed through the decoder pipeline for integration testing.

## Recording real data

To capture real WWVB reception data for offline replay:

1. Connect to SDRConnect with the tool running in `--debug` mode
2. The raw audio samples will be logged
3. Save the output for replay testing
