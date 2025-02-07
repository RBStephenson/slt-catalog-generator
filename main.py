import os
import logging
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, UnidentifiedImageError
from jinja2 import Template

# Configure logging
logging.basicConfig(
    filename="stl_catalog_errors.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def copy_and_resize_image(original_path: Path, local_image_path: Path, max_size=(300, 300)):
    """
    Copy and resize a single image if needed, with robust error handling.
    Returns the path to the local image if successful, or None if failed.
    """
    try:
        if not local_image_path.exists() or original_path.stat().st_mtime > local_image_path.stat().st_mtime:
            with Image.open(original_path) as img:
                img.thumbnail(max_size)
                img.save(local_image_path)
            print(f"Resized and copied image: {original_path} -> {local_image_path}")
        # Return relative path (for HTML usage) if all goes well
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
    Copies images to a local `img` folder, resizing them if necessary.
    Uses concurrency to speed up processing. Logs errors and continues.
    """
    if not img_folder.exists():
        img_folder.mkdir(parents=True, exist_ok=True)

    # Dictionary to track which Future belongs to which model/image data
    future_to_meta = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for base_path, creators in catalog.items():
            for creator, releases in creators.items():
                for release, models in releases.items():
                    for model, data in models.items():
                        new_image_paths = []
                        for image in data.get("images", []):
                            original_path = Path(image)
                            if original_path.exists() and original_path.is_file():
                                image_filename = original_path.name
                                local_image_path = img_folder / image_filename
                                # Submit tasks to resize and copy
                                future = executor.submit(
                                    copy_and_resize_image,
                                    original_path,
                                    local_image_path,
                                    max_size
                                )
                                # Map the future to the metadata we’ll need later
                                future_to_meta[future] = (model, new_image_paths, image_filename)

                        # NOTE: We'll set data["images"] to new_image_paths
                        # after we retrieve results from futures below
                        data["images"] = new_image_paths

    # Now gather the results in completion order:
    for future in as_completed(future_to_meta):
        model, new_image_paths, image_filename = future_to_meta[future]
        result = future.result()  # This will be None if something failed or path if success
        if result:
            # We only want the relative path for HTML usage
            new_image_paths.append(str(Path("img") / image_filename))


def scan_directories(base_paths):
    """
    Scans multiple directories recursively, categorizing STL-related files.
    Organizes them by Base Directory -> Creator -> Release -> Model structure.
    """
    catalog = {}

    for base_path_str in base_paths:
        base_path = Path(base_path_str).resolve()
        print(f"Starting directory scan: {base_path}")

        for root, _, files in os.walk(base_path):
            root_path = Path(root)
            relative_path = root_path.relative_to(base_path)
            parts = relative_path.parts

            # Identify category based on folder depth
            if len(parts) < 1:
                creator, release, model_name = "Misc Files", "", ""
            else:
                # Note: you can tweak the logic below to fit your folder structure exactly
                creator = parts[0] if len(parts) > 0 else "Misc Files"
                release = parts[1] if len(parts) > 1 else "Unknown Release"
                model_name = parts[-1] if len(parts) > 2 else "Unknown Model"

            # Ensure base path exists in catalog
            if base_path_str not in catalog:
                catalog[base_path_str] = {}
            if creator not in catalog[base_path_str]:
                catalog[base_path_str][creator] = {}
            if release not in catalog[base_path_str][creator]:
                catalog[base_path_str][creator][release] = {}
            if model_name not in catalog[base_path_str][creator][release]:
                catalog[base_path_str][creator][release][model_name] = {
                    "files": [],
                    "images": [],
                    "slicer_files": []
                }

            print(f"Scanning folder: {relative_path}")
            # Categorize files within the model directory
            for file in files:
                file_path = root_path / file
                if not file_path.is_file():
                    continue

                ext = file_path.suffix.lower().lstrip('.')
                if ext in ["jpg", "png"]:
                    catalog[base_path_str][creator][release][model_name]["images"].append(str(file_path))
                elif ext in ["lys", "chitubox"]:
                    catalog[base_path_str][creator][release][model_name]["slicer_files"].append(str(file_path))
                else:
                    catalog[base_path_str][creator][release][model_name]["files"].append(str(file_path))

    print("Directory scan complete.")
    return catalog


def remove_empty_entries(catalog: dict) -> dict:
    """
    Removes empty models, releases, creators, and base_paths
    from the catalog structure in-place.
    Returns the pruned catalog reference.
    """
    empty_base_paths = []

    for base_path, creators in catalog.items():
        empty_creators = []

        for creator, releases in creators.items():
            empty_releases = []

            for release, models in releases.items():
                empty_models = []

                for model, data in models.items():
                    # Check if this model is truly empty (no files, no images, no slicer files)
                    if not data["files"] and not data["images"] and not data["slicer_files"]:
                        empty_models.append(model)

                # Remove the empty models
                for em in empty_models:
                    del models[em]

                # If there are no models left in this release, it’s empty
                if not models:
                    empty_releases.append(release)

            # Remove the empty releases
            for er in empty_releases:
                del releases[er]

            # If there are no releases left for this creator, mark it as empty
            if not releases:
                empty_creators.append(creator)

        # Remove the empty creators
        for ec in empty_creators:
            del creators[ec]

        # If no creators remain under this base path, it’s empty
        if not creators:
            empty_base_paths.append(base_path)

    # Remove completely empty base paths
    for ebp in empty_base_paths:
        del catalog[ebp]

    return catalog


def generate_html(catalog, output_file: Path):
    """
    Generates an HTML file displaying the categorized STL models
    with Bootstrap accordions, a "Collapse All" button, and a
    floating "Back to Top" button.
    """
    print("Generating HTML output...")

    template_str = r"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title>STL Catalog</title>

        <!-- Bootstrap 5.3.1 CSS (via CDN with matching integrity) -->
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">
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
            /* Floating Back to Top Button */
            #backToTopBtn {
                display: none;
                position: fixed;
                bottom: 40px;
                right: 40px;
                z-index: 99;
            }
        </style>
    </head>
    <body class="bg-light">
        <div class="container my-5">
            <h1 class="mb-4">STL Catalog</h1>

            <!-- Collapse All button -->
            <button onclick="collapseAllAccordions()" 
                    class="btn btn-outline-secondary mb-4">
                Collapse All
            </button>

            <!-- Outer accordion for Base Directories -->
            <div class="accordion" id="accordionBaseDirs">
                {% for base_path, creators in catalog.items() %}
                <div class="accordion-item">
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
                                {% for creator, releases in creators.items() %}
                                <div class="accordion-item">
                                    <h2 class="accordion-header" 
                                        id="heading-{{ loop.index }}-{{ loop.index0 }}">
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
                                            <div class="accordion" 
                                                 id="accordionReleases-{{ loop.index }}-{{ loop.index0 }}">
                                                {% for release, models in releases.items() %}
                                                <div class="accordion-item">
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
                                                            {% for model, data in models.items() %}
                                                            <div class="model mb-3">
                                                                <h5 class="fw-bold">{{ model }}</h5>
                                                                <div class="file-list">
                                                                    <p class="text-muted mb-1">Source files:</p>
                                                                    <ul class="list-unstyled">
                                                                        {% for f in data.get("files", []) %}
                                                                        <li>
                                                                            <a href="file://{{ f }}" target="_blank">
                                                                                {{ f }}
                                                                            </a>
                                                                        </li>
                                                                        {% endfor %}
                                                                        {% for s in data.get("slicer_files", []) %}
                                                                        <li class="slicer-file">
                                                                            <a href="file://{{ s }}" target="_blank">
                                                                                {{ s }}
                                                                            </a>
                                                                        </li>
                                                                        {% endfor %}
                                                                    </ul>
                                                                </div>
                                                                <div>
                                                                    {% for image in data.get("images", []) %}
                                                                    <img src="{{ image }}" width="150" loading="lazy" class="border">
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

        <!-- Back to Top Button -->
        <button id="backToTopBtn" class="btn btn-primary" title="Go to top" onclick="topFunction()">
            ↑ Top
        </button>

        <!-- Bootstrap JS (5.3.1) -->
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>

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

            // Collapse all open accordions via Bootstrap's API
            function collapseAllAccordions() {
                // Find all accordion collapse elements currently 'shown'
                const openAccordions = document.querySelectorAll('.accordion-collapse.show');
                openAccordions.forEach(collapseEl => {
                    // Get or create the Bootstrap Collapse instance for each element
                    const bsCollapse = bootstrap.Collapse.getOrCreateInstance(collapseEl);
                    bsCollapse.hide();  // programmatically hide it
                });
            }
        </script>
    </body>
    </html>
    """

    from jinja2 import Template
    template = Template(template_str)
    html_content = template.render(catalog=catalog)
    output_file.write_text(html_content, encoding="utf-8")
    print(f"HTML catalog generated: {output_file}")


def main():
    """
    Main function to execute the directory scan, resize images, and generate the HTML catalog.
    """
    base_paths_input = input("Enter the paths to your STL collections (comma-separated): ").strip()
    base_paths = [p.strip() for p in base_paths_input.split(',')]
    output_file = Path("stl_catalog.html")
    img_folder = Path("img")

    print("Starting STL catalog generation...")
    catalog = scan_directories(base_paths)
    catalog = remove_empty_entries(catalog)  # This prunes empty stuff
    copy_and_resize_images(catalog, img_folder)
    generate_html(catalog, output_file)
    copy_and_resize_images(catalog, img_folder)
    generate_html(catalog, output_file)
    print("Process completed successfully!")


if __name__ == "__main__":
    main()
