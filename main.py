import os
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, UnidentifiedImageError
from jinja2 import Environment, Template

# Configure logging
logging.basicConfig(
    filename="stl_catalog_errors.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def convert_file_size(num_bytes):
    """
    Convert a file size in bytes to a more readable string like '123 KB'.
    """
    for unit in ['B','KB','MB','GB','TB']:
        if num_bytes < 1024:
            return f"{num_bytes:.0f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.0f} PB"

def copy_and_resize_image(original_path: Path, local_image_path: Path, max_size=(300, 300)):
    """
    Copy and resize a single image if needed, with robust error handling.
    Returns the local thumbnail path if successful, or None if failed.
    """
    try:
        # Only regenerate if original is newer or thumbnail doesn't exist
        if (not local_image_path.exists() or
                original_path.stat().st_mtime > local_image_path.stat().st_mtime):
            with Image.open(original_path) as img:
                img.thumbnail(max_size)
                img.save(local_image_path)
            print(f"Resized and copied image: {original_path} -> {local_image_path}")
        return str(local_image_path)
    except UnidentifiedImageError:
        logging.error(f"Unidentified image file: {original_path}")
        print(f"Error: Cannot process image {original_path}. Logged to file.")
    except PermissionError:
        logging.error(f"Permission error while accessing {original_path}")
        print(f"Error: Permission denied for {original_path}. Logged to file.")
    except Exception as e:
        logging.error(f"Error processing {original_path}: {str(e)}")
        print(f"Error: {str(e)} - Logged to file.")

    return None

def copy_and_resize_images(catalog, img_folder: Path, max_size=(300, 300), max_workers=4):
    """
    For each image in the catalog, create a thumbnail in `img` folder.
    We keep track of both the full-sized original and the thumbnail path in the model data.
    Uses concurrency to speed up the process.
    """
    if not img_folder.exists():
        img_folder.mkdir(parents=True, exist_ok=True)

    future_to_meta = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for base_path, creators in catalog.items():
            for creator, releases in creators.items():
                for release, models in releases.items():
                    for model_name, data in models.items():
                        # We'll store the original/thumbnail pairs separately
                        data.setdefault("images_original", [])
                        data.setdefault("images_thumbs", [])

                        # Anything in "images" will be processed for thumbnails
                        for img_entry in data["images"]:
                            original_path = Path(img_entry["path"])
                            if original_path.exists() and original_path.is_file():
                                local_image_path = img_folder / original_path.name
                                future = executor.submit(
                                    copy_and_resize_image,
                                    original_path,
                                    local_image_path,
                                    max_size
                                )
                                # Map the future to (data, original_path)
                                future_to_meta[future] = (data, original_path)

                        # Clear out "images" so we don't double-process
                        data["images"] = []

    # Gather thumbnail results
    for future in as_completed(future_to_meta):
        data, original_path = future_to_meta[future]
        thumb_path = future.result()
        if thumb_path:
            data["images_original"].append(str(original_path))
            data["images_thumbs"].append(thumb_path)

def scan_directories(base_paths):
    """
    Scans multiple directories recursively, building a nested structure:
      catalog[base_path][creator][release][model] = {
          "slicer_files": [ {path, size, ext}, ... ],
          "stl_files":    [ {path, size, ext}, ... ],
          "files":        [ {path, size, ext}, ... ],
          "images":       [ {path, size, ext}, ... ]
      }

    - If .zip, put in a "Zip" release category.
    - We also store file size and extension for icons/UX improvements later.
    - If we don't have enough folder depth to guess a "model", we just use the folder's name.
    """
    catalog = {}

    for base_path_str in base_paths:
        base_path = Path(base_path_str).resolve()
        print(f"Starting directory scan: {base_path}")

        for root, _, files in os.walk(base_path):
            root_path = Path(root)
            relative_path = root_path.relative_to(base_path)
            parts = relative_path.parts

            if len(parts) == 0:
                creator = "Misc Files"
                release = ""
                model_name = root_path.name
            else:
                creator = parts[0] if len(parts) >= 1 else "Misc Files"
                release = parts[1] if len(parts) >= 2 else "Unknown Release"
                model_name = parts[-1] if len(parts) >= 3 else root_path.name

            if base_path_str not in catalog:
                catalog[base_path_str] = {}
            if creator not in catalog[base_path_str]:
                catalog[base_path_str][creator] = {}
            if release not in catalog[base_path_str][creator]:
                catalog[base_path_str][creator][release] = {}
            if model_name not in catalog[base_path_str][creator][release]:
                catalog[base_path_str][creator][release][model_name] = {
                    "slicer_files": [],
                    "stl_files": [],
                    "files": [],
                    "images": []
                }

            print(f"Scanning folder: {relative_path}")
            for filename in files:
                file_path = root_path / filename
                if not file_path.is_file():
                    continue
                ext = file_path.suffix.lower().lstrip('.')
                size_str = convert_file_size(file_path.stat().st_size)

                # If it's a .zip, override the release to "Zip"
                if ext == "zip":
                    release_key = "Zip"
                    if release_key not in catalog[base_path_str][creator]:
                        catalog[base_path_str][creator][release_key] = {}
                    if model_name not in catalog[base_path_str][creator][release_key]:
                        catalog[base_path_str][creator][release_key][model_name] = {
                            "slicer_files": [],
                            "stl_files": [],
                            "files": [],
                            "images": []
                        }
                    catalog[base_path_str][creator][release_key][model_name]["files"].append({
                        "path": str(file_path),
                        "size": size_str,
                        "ext": ext
                    })

                elif ext in ["jpg", "jpeg", "png"]:
                    catalog[base_path_str][creator][release][model_name]["images"].append({
                        "path": str(file_path),
                        "size": size_str,
                        "ext": ext
                    })

                elif ext in ["lys", "chitubox"]:
                    catalog[base_path_str][creator][release][model_name]["slicer_files"].append({
                        "path": str(file_path),
                        "size": size_str,
                        "ext": ext
                    })

                elif ext in ["stl"]:
                    catalog[base_path_str][creator][release][model_name]["stl_files"].append({
                        "path": str(file_path),
                        "size": size_str,
                        "ext": ext
                    })

                else:
                    catalog[base_path_str][creator][release][model_name]["files"].append({
                        "path": str(file_path),
                        "size": size_str,
                        "ext": ext
                    })

    print("Directory scan complete.")
    return catalog

def remove_empty_entries(catalog: dict) -> dict:
    """
    Removes empty models, releases, creators, and base_paths from the structure.
    Returns the pruned catalog.
    """
    empty_base_paths = []
    for base_path, creators in catalog.items():
        empty_creators = []

        for creator, releases in creators.items():
            empty_releases = []
            for release, models in releases.items():
                empty_models = []
                for model, data in models.items():
                    # check if everything is empty
                    no_stls = not data["stl_files"]
                    no_slicers = not data["slicer_files"]
                    no_images = not data["images"]
                    no_files = not data["files"]
                    no_images_orig = not data.get("images_original")
                    no_images_thumbs = not data.get("images_thumbs")
                    if all([no_stls, no_slicers, no_images, no_files, no_images_orig, no_images_thumbs]):
                        empty_models.append(model)

                for em in empty_models:
                    del models[em]

                if not models:
                    empty_releases.append(release)

            for er in empty_releases:
                del releases[er]

            if not releases:
                empty_creators.append(creator)

        for ec in empty_creators:
            del creators[ec]

        if not creators:
            empty_base_paths.append(base_path)

    for ebp in empty_base_paths:
        del catalog[ebp]

    return catalog

def generate_html(catalog, output_file: Path):
    """
    Generates an HTML file with:
     - Sorted base_path, creators, releases, models
     - Filetype icons (Bootstrap Icons)
     - Lightbox-style modal for images
     - File sizes
     - Client-side search
     - Toggle Thumbnails button
    """

    template_str = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>STL Catalog</title>

    <!-- Bootstrap CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
          rel="stylesheet"
          integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
          crossorigin="anonymous">
    <!-- Bootstrap Icons -->
    <link rel="stylesheet"
          href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">

    <style>
        .model img {
            margin-right: 10px;
            margin-bottom: 10px;
            border: 1px solid #ccc;
        }
        .slicer-file {
            font-weight: bold;
            color: red;
        }
        .file-list {
            margin-top: 0.5rem;
        }
        /* For toggling thumbnail containers on/off */
        .thumbnails-container {
            transition: 0.3s ease;
        }
        /* Floating Back to Top Button */
        #backToTopBtn {
            display: none;
            position: fixed;
            bottom: 40px;
            right: 40px;
            z-index: 99;
        }
        /* Hide elements not matching search */
        .hidden-by-search {
            display: none !important;
        }
    </style>
</head>
<body class="bg-light">
    <div class="container my-5">
        <h1 class="mb-4">STL Catalog</h1>

        <!-- Search Field -->
        <div class="mb-3">
            <label for="searchInput" class="form-label">Search:</label>
            <input type="text" id="searchInput" class="form-control"
                   placeholder="Type to filter... (model, release, creator, or base path)">
        </div>

        <!-- Buttons -->
        <div class="d-flex gap-2 mb-4">
            <button onclick="collapseAllAccordions()" class="btn btn-outline-secondary">
                Collapse All
            </button>
            <button onclick="toggleThumbnails()" class="btn btn-outline-secondary" id="toggleThumbsBtn">
                Hide Thumbnails
            </button>
        </div>

        <!-- Outer accordion for Base Directories -->
        <div class="accordion" id="accordionBaseDirs">
            {% for base_path, creators in catalog|dictsort %}
            <div class="accordion-item" 
                 data-filter-text="{{ base_path|lower }}">
                <h2 class="accordion-header" id="heading-{{ loop.index }}">
                    <button class="accordion-button collapsed"
                            type="button"
                            data-bs-toggle="collapse"
                            data-bs-target="#collapse-{{ loop.index }}"
                            aria-expanded="false"
                            aria-controls="collapse-{{ loop.index }}">
                        Base Directory: {{ base_path }}
                    </button>
                </h2>
                <div id="collapse-{{ loop.index }}"
                     class="accordion-collapse collapse"
                     aria-labelledby="heading-{{ loop.index }}"
                     data-bs-parent="#accordionBaseDirs">
                    <div class="accordion-body">

                        <!-- Nested accordion for Creators -->
                        <div class="accordion" id="accordionCreators-{{ loop.index }}">
                            {% for creator, releases in creators|dictsort %}
                            <div class="accordion-item"
                                 data-filter-text="{{ creator|lower }} {{ base_path|lower }}">
                                <h2 class="accordion-header" id="heading-{{ loop.index }}-{{ loop.index0 }}">
                                    <button class="accordion-button collapsed"
                                            type="button"
                                            data-bs-toggle="collapse"
                                            data-bs-target="#collapse-{{ loop.index }}-{{ loop.index0 }}"
                                            aria-expanded="false"
                                            aria-controls="collapse-{{ loop.index }}-{{ loop.index0 }}">
                                        {{ creator }}
                                    </button>
                                </h2>
                                <div id="collapse-{{ loop.index }}-{{ loop.index0 }}"
                                     class="accordion-collapse collapse"
                                     aria-labelledby="heading-{{ loop.index }}-{{ loop.index0 }}"
                                     data-bs-parent="#accordionCreators-{{ loop.index }}">
                                    <div class="accordion-body">

                                        <!-- Another accordion for Releases -->
                                        <div class="accordion" id="accordionReleases-{{ loop.index }}-{{ loop.index0 }}">
                                            {% for release, models in releases|dictsort %}
                                            <div class="accordion-item"
                                                 data-filter-text="{{ release|lower }} {{ creator|lower }} {{ base_path|lower }}">
                                                <h2 class="accordion-header"
                                                    id="heading-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}">
                                                    <button class="accordion-button collapsed"
                                                            type="button"
                                                            data-bs-toggle="collapse"
                                                            data-bs-target="#collapse-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}"
                                                            aria-expanded="false"
                                                            aria-controls="collapse-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}">
                                                        {{ release if release else 'Misc Files' }}
                                                    </button>
                                                </h2>
                                                <div id="collapse-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}"
                                                     class="accordion-collapse collapse"
                                                     aria-labelledby="heading-{{ loop.index }}-{{ loop.index0 }}-{{ loop.index1 }}"
                                                     data-bs-parent="#accordionReleases-{{ loop.index }}-{{ loop.index0 }}">
                                                    <div class="accordion-body">

                                                        <!-- Models Listing -->
                                                        {% for model_name, data in models|dictsort %}
                                                        <div class="model mb-3"
                                                             data-filter-text="{{ model_name|lower }} {{ release|lower }} {{ creator|lower }} {{ base_path|lower }}">
                                                            <h5 class="fw-bold">{{ model_name }}</h5>
                                                            <div class="file-list">
                                                                <p class="text-muted mb-1">Files:</p>
                                                                <ul class="list-unstyled">

                                                                    <!-- Slicer files first -->
                                                                    {% for slicer in data.get("slicer_files", []) %}
                                                                    <li class="slicer-file d-flex align-items-center">
                                                                        <i class="bi {{ slicer.ext|file_icon }} me-1"></i>
                                                                        <a href="file://{{ slicer.path|dirname }}"
                                                                           target="_blank">
                                                                            [Open Folder]
                                                                        </a>
                                                                        - {{ slicer.path }} ({{ slicer.size }})
                                                                    </li>
                                                                    {% endfor %}

                                                                    <!-- Then STL files -->
                                                                    {% for stl in data.get("stl_files", []) %}
                                                                    <li class="d-flex align-items-center">
                                                                        <i class="bi {{ stl.ext|file_icon }} me-1"></i>
                                                                        <a href="file://{{ stl.path|dirname }}"
                                                                           target="_blank">
                                                                            [Open Folder]
                                                                        </a>
                                                                        - {{ stl.path }} ({{ stl.size }})
                                                                    </li>
                                                                    {% endfor %}

                                                                    <!-- Then general "other" files -->
                                                                    {% for f in data.get("files", []) %}
                                                                    <li class="d-flex align-items-center">
                                                                        <i class="bi {{ f.ext|file_icon }} me-1"></i>
                                                                        <a href="file://{{ f.path|dirname }}"
                                                                           target="_blank">
                                                                            [Open Folder]
                                                                        </a>
                                                                        - {{ f.path }} ({{ f.size }})
                                                                    </li>
                                                                    {% endfor %}
                                                                </ul>
                                                            </div>

                                                            <!-- Thumbnails Container -->
                                                            <div class="thumbnails-container">
                                                                {% for i in range(data.get("images_thumbs", [])|length) %}
                                                                    {% set thumb = data.images_thumbs[i] %}
                                                                    {% set orig = data.images_original[i] %}
                                                                    <img  src="{{ thumb }}"
                                                                          alt="thumbnail"
                                                                          class="border catalog-thumbnail"
                                                                          width="150"
                                                                          loading="lazy"
                                                                          data-fullsize="{{ orig }}"
                                                                          style="cursor:pointer;">
                                                                {% endfor %}
                                                            </div>
                                                        </div>
                                                        {% endfor %}
                                                    </div>
                                                </div>
                                            </div>
                                            {% endfor %}
                                        </div> <!-- End accordionReleases -->

                                    </div>
                                </div>
                            </div>
                            {% endfor %}
                        </div> <!-- End accordionCreators -->

                    </div>
                </div>
            </div>
            {% endfor %}
        </div> <!-- End accordionBaseDirs -->
    </div> <!-- container -->

    <!-- Modal for Lightbox -->
    <div class="modal fade" id="imageModal" tabindex="-1" aria-labelledby="imageModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-dialog-centered modal-xl">
        <div class="modal-content">
          <div class="modal-body p-0" style="text-align:center;">
            <img id="modal-img" src="" alt="" style="max-width: 100%; height:auto;">
          </div>
          <button type="button" class="btn-close position-absolute top-0 end-0 p-3"
                  data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
      </div>
    </div>

    <!-- Back to Top Button -->
    <button id="backToTopBtn" class="btn btn-primary" title="Go to top" onclick="topFunction()">
        ↑ Top
    </button>

    <!-- Bootstrap Bundle JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
            integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz"
            crossorigin="anonymous"></script>

    <script>
        // Show/hide Back to Top button upon scrolling
        const backToTopBtn = document.getElementById("backToTopBtn");
        window.addEventListener("scroll", () => {
            if (document.documentElement.scrollTop > 300) {
                backToTopBtn.style.display = "block";
            } else {
                backToTopBtn.style.display = "none";
            }
        });

        // Scroll to top smoothly
        function topFunction() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        // Collapse all open accordions
        function collapseAllAccordions() {
            const openAccordions = document.querySelectorAll('.accordion-collapse.show');
            openAccordions.forEach(collapseEl => {
                const bsCollapse = bootstrap.Collapse.getOrCreateInstance(collapseEl);
                bsCollapse.hide();
            });
        }

        // Toggle show/hide all thumbnail containers
        let thumbsAreVisible = true;
        function toggleThumbnails() {
            const thumbBtn = document.getElementById("toggleThumbsBtn");
            const containers = document.querySelectorAll('.thumbnails-container');
            thumbsAreVisible = !thumbsAreVisible;
            containers.forEach(el => {
                el.style.display = thumbsAreVisible ? '' : 'none';
            });
            thumbBtn.textContent = thumbsAreVisible ? 'Hide Thumbnails' : 'Show Thumbnails';
        }

        // Lightbox (modal) for images
        document.addEventListener('click', function(e) {
            if (e.target.matches('.catalog-thumbnail')) {
                const fullSizeUrl = e.target.dataset.fullsize;
                const modalImg = document.getElementById('modal-img');
                modalImg.src = "file://" + fullSizeUrl;
                const imageModal = new bootstrap.Modal(document.getElementById('imageModal'));
                imageModal.show();
            }
        });

        // Client-side search
        const searchInput = document.getElementById('searchInput');
        searchInput.addEventListener('input', function() {
            const query = searchInput.value.toLowerCase().trim();
            // We want to hide .accordion-item or .model that doesn't match
            // We'll match on the data-filter-text attribute which includes base_path/creator/release/model
            const filterableEls = document.querySelectorAll('.accordion-item, .model');
            filterableEls.forEach(el => {
                const text = el.getAttribute('data-filter-text') || '';
                if (text.includes(query)) {
                    el.classList.remove('hidden-by-search');
                } else {
                    el.classList.add('hidden-by-search');
                }
            });
        });
    </script>
</body>
</html>
    """

    # We'll define a small dictionary for icons keyed by extension
    file_icons = {
        "zip": "bi-file-earmark-zip-fill",
        "stl": "bi-file-earmark",
        "lys": "bi-file-binary-fill",
        "chitubox": "bi-file-binary-fill",
        "jpg": "bi-file-image",
        "jpeg": "bi-file-image",
        "png": "bi-file-image"
    }

    def file_icon_filter(ext):
        return file_icons.get(ext.lower(), "bi-file-earmark")

    # Jinja environment with custom filters
    env = Environment()
    env.filters["dirname"] = lambda path_str: str(Path(path_str).parent)
    env.filters["file_icon"] = file_icon_filter

    template = env.from_string(template_str)
    html_content = template.render(catalog=catalog)
    output_file.write_text(html_content, encoding="utf-8")
    print(f"HTML catalog generated: {output_file}")

def main():
    """
    Main function to run the directory scan, copy/resize images, and generate the HTML catalog.
    """
    base_paths_input = input("Enter the paths to your STL collections (comma-separated): ").strip()
    base_paths = [p.strip() for p in base_paths_input.split(',')]
    output_file = Path("stl_catalog.html")
    img_folder = Path("img")

    print("Starting STL catalog generation...")
    catalog = scan_directories(base_paths)
    remove_empty_entries(catalog)
    copy_and_resize_images(catalog, img_folder)
    generate_html(catalog, output_file)
    print("Process completed successfully!")

if __name__ == "__main__":
    main()
