import io
import httpx
from PIL import Image, ExifTags

async def analyze_image_for_tampering(file_url: str) -> tuple[bool, dict]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(file_url, timeout=10.0)
            if response.status_code != 200:
                return False, {"error": f"Could not download image, status: {response.status_code}"}
            
            image_data = response.content
            
        img = Image.open(io.BytesIO(image_data))
        
        is_tampered = False
        metadata = {}
        
        # Check EXIF
        exif = img.getexif()
        if exif:
            for tag_id, value in exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, tag_id)
                # Convert bytes or un-serializable types to string
                try:
                    metadata[str(tag_name)] = str(value)
                except Exception:
                    pass
                
                # Check software tag for known editing software
                if tag_name == "Software" and isinstance(value, str):
                    software = value.lower()
                    if any(x in software for x in ["photoshop", "gimp", "lightroom", "canva", "snapseed", "illustrator", "paint"]):
                        is_tampered = True
                        
        metadata["format"] = img.format
        metadata["mode"] = img.mode
        metadata["size"] = img.size
        
        return is_tampered, metadata
        
    except Exception as e:
        return False, {"error": f"Analysis failed: {str(e)}"}
