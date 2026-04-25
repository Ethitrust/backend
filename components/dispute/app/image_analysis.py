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
                        
        # Error Level Analysis (ELA)
        try:
            from PIL import ImageChops, ImageEnhance
            # Save at known quality
            resaved_io = io.BytesIO()
            img.convert('RGB').save(resaved_io, 'JPEG', quality=90)
            resaved_io.seek(0)
            resaved_img = Image.open(resaved_io)
            
            # Calculate difference
            ela_img = ImageChops.difference(img.convert('RGB'), resaved_img)
            extrema = ela_img.getextrema()
            max_diff = max([ex[1] for ex in extrema])
            
            metadata["ela_max_difference"] = max_diff
            if max_diff > 50:  # Arbitrary threshold for significant editing
                is_tampered = True
                metadata["ela_flagged"] = True
        except Exception as ela_e:
            metadata["ela_error"] = str(ela_e)
            
        metadata["format"] = img.format
        metadata["mode"] = img.mode
        metadata["size"] = img.size
        
        return is_tampered, metadata
        
    except Exception as e:
        return False, {"error": f"Analysis failed: {str(e)}"}
