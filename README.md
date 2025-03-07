
# STL Catalog Generator

A Python-based script to automatically scan directories containing STL (and related) files, generate thumbnail images, and build an interactive HTML “catalog” of all your 3D model files. This is useful for quickly browsing your 3D-printing collection in a friendly, visual manner.

## Features

- **Recursive Directory Scan**: Organizes files by **Base Path → Creator → Release → Model**.
- **Automatic Thumbnails**: Uses [Pillow (PIL)](https://pypi.org/project/Pillow/) to resize images into thumbnails.
- **Slicer File & Zip Handling**: Groups `.lys` and `.chitubox` separately from `.stl` files, and moves all `.zip` files into a `Zip` release category.
- **Icons & Lightbox**: Displays Bootstrap Icons for various file types. Clicking a thumbnail opens a lightbox-style modal (no new tab).
- **Client-Side Search**: Quickly filter your entire catalog by typing a partial match of the base path, creator, release, or model name.
- **Toggle Thumbnails**: Easily show/hide all thumbnails to reduce scrolling.
- **Collapse All**: One button collapses all open accordions, helping you keep the interface tidy.
- **File Sizes**: Displays the size of each file (e.g., `123 KB`).

## Prerequisites

- **Python 3.7+** (or newer)
- A virtual environment is recommended but optional.

## Installation

1. **Clone or Download** this repository.
2. (Optional) Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # on macOS/Linux
   .venv\Scripts\activate     # on Windows
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   If you don’t have a `requirements.txt`, install individually:
   ```bash
   pip install pillow jinja2
   ```

## Usage

1. Run the main script:
   ```bash
   python main.py
   ```
2. When prompted, enter one or more **comma-separated paths** to the folders containing your STL files. For example:
   ```
   Enter the paths to your STL collections (comma-separated):
   C:\3D\MyModels, C:\3D\Archive
   ```
3. The script:
   - Recursively scans each path.
   - Generates thumbnails for `.jpg`, `.jpeg`, and `.png` images.
   - Categorizes `.zip`, `.stl`, `.lys`, `.chitubox`, etc.
   - Creates an **`stl_catalog.html`** file in the same directory as the script.
   - Creates an **`img`** folder containing thumbnails.

4. **Open** the generated `stl_catalog.html` in your browser. You should see an organized, clickable catalog of your files.

### Search

- Use the **Search** input at the top to filter by partial or full matches of:
  - Base path
  - Creator
  - Release
  - Model name

As you type, rows that **don’t** match your text are hidden in real-time.

### Toggling Thumbnails

- Click **“Hide Thumbnails”** (or “Show Thumbnails”) to toggle visibility of all image thumbnails.

### Collapsing All

- Use the **“Collapse All”** button to close all open accordions at once.

## Configuration & Tweaks

- **Thumbnail Size**: Adjust `max_size=(300, 300)` in `copy_and_resize_images` if you want larger or smaller thumbnails.
- **File Icons**: The script uses [Bootstrap Icons](https://icons.getbootstrap.com/) for certain known file extensions. You can add more to the `file_icons` dictionary in the code.
- **Advanced Sorting**: By default, we alphabetically sort dictionary keys in ascending order. If you need more control (e.g., sorting by date or folder size), modify the loops in `generate_html`.
- **Concurrency**: Thumbnails are generated in parallel using `ThreadPoolExecutor(max_workers=4)`. Increase `max_workers` if you have a ton of images and a powerful CPU.

## Troubleshooting

1. **No Results on Search**: Make sure the search text exactly matches (ignoring case) the words in either the folder name, creator, release, or model name.  
2. **Permission Errors**: If you see “Permission denied,” check that your script has read access to the directories and write access to create the `img` folder.  
3. **Missing Thumbnails**: Verify that your images are `.jpg`, `.jpeg`, or `.png`. Other formats aren’t currently resized. If needed, add more extensions in the code where images are handled.

## Contributing

Feel free to open PRs or issues to suggest improvements or bug fixes. If you have specific ideas (custom grouping logic, additional file-type handling, etc.), we’d love to see them!

## License

MIT License. See [LICENSE](LICENSE) for more details.