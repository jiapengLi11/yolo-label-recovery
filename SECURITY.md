# Security and privacy

This tool is designed to process local datasets. Do not upload private camera frames, employee images, site layouts, credentials or proprietary model weights to a public repository.

Before publishing an experiment:

1. Remove images, labels, `.pt` files, logs and generated outputs.
2. Replace absolute paths with relative example paths.
3. Check Git history, not only the working tree.
4. Confirm that `data.yaml` contains no private directories or URLs.

