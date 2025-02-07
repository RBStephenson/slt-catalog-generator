# STL Catalog Generator

A Python-based tool to scan directories of STL (and related) files, generate a structured catalog, and produce a fancy (Bootstrap-powered) HTML page. Because who doesn’t love a sweet visual index?

## Features

- **Recursive Directory Scan**: Automatically categorizes files into creators, releases, and models.  
- **Image Processing**: Resizes `jpg`/`png` images for a thumbnail gallery (lazy-load for extra speed).  
- **Concurrency**: Uses `ThreadPoolExecutor` for faster image copy/resize.  
- **Bootstrap UI**: Collapsible accordions, “Back to Top” button, and a “Collapse All” feature for easy navigation.  
- **Error Handling**: Logs issues (like unreadable images) to `stl_catalog_errors.log`.

## Requirements

- **Python** 3.7+ (Recommended 3.9+)
- [Pillow](https://pillow.readthedocs.io/en/stable/) for image processing
- [Jinja2](https://pypi.org/project/Jinja2/) for HTML templating
- (Optional) [pytest](https://docs.pytest.org/) for unit tests

Install them via:

```bash
pip install pillow jinja2 pytest
```

## Usage

1. **Clone or Download** the repo.
2. **Run** the script:
   ```bash
   python main.py
   ```
3. **Enter Paths**: When prompted, provide one or more directory paths (comma-separated) that contain your STL collection.
4. **Result**: 
   - A file named `stl_catalog.html` in your project directory.  
   - An `img/` folder containing resized image thumbnails.  
   - A `stl_catalog_errors.log` file if any issues come up.

Open `stl_catalog.html` in your web browser—voilà!

## Configuration

- **Parallel Image Processing**  
  Tweak `max_workers` in `copy_and_resize_images()` to control how many images are processed concurrently.
- **Thumbnail Size**  
  Adjust the `max_size` parameter (e.g., `(300, 300)`) to change your thumbnail dimensions.
- **HTML Styling**  
  Custom CSS or different frameworks can be updated in `generate_html` if you’re feeling adventurous.

## Hiding Empty Folders

If you have subfolders with no actual content, you can prune them by calling `remove_empty_entries(catalog)` or adding conditional checks in the Jinja template. This tidies up your final HTML output.

## Tests

We included a sample `test_stl_catalog.py` using `pytest`.  
Run them with:

```bash
pytest test_stl_catalog.py
```

This spins up a temp directory with dummy files, ensuring our scanning and resizing logic behaves.

## Contributing

1. **Fork** the project  
2. **Create** your feature branch  
3. **Commit** your changes  
4. **Open** a Pull Request

All feedback, suggestions, and bug reports are welcome—especially new ways to keep your 2.5 TB of STL files neat and tidy.

## License

[MIT License](LICENSE) – or any license that suits your fancy.
