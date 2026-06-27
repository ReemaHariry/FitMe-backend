import cv2
import os

def extract_frames_from_video(video_path, output_dir, fps=5):
    """
    Extract frames from a video at a specified FPS and save them as images.

    Args:
        video_path (str): Path to the video file.
        output_dir (str): Directory to save extracted frames.
        fps (int): Frames per second to extract.
    """
    os.makedirs(output_dir, exist_ok=True)
    video = cv2.VideoCapture(video_path)
    
    if not video.isOpened():
        raise ValueError(f"Error opening video file: {video_path}")

    # Video properties
    video_fps = video.get(cv2.CAP_PROP_FPS)
    frame_interval = int(video_fps / fps)  # Skip frames to match desired FPS

    frame_count = 0
    saved_count = 0

    while True:
        ret, frame = video.read()
        if not ret:
            break  # End of video
        
        if frame_count % frame_interval == 0:
            frame_name = f"frame_{saved_count:05d}.png"
            frame_path = os.path.join(output_dir, frame_name)
            cv2.imwrite(frame_path, frame)
            saved_count += 1
        
        frame_count += 1

    video.release()
    print(f"Extracted {saved_count} frames from {video_path} into {output_dir}.")

def get_next_directory(output_base_dir):
    """
    Get the next available directory number to ensure the output directory is numbered sequentially.

    Args:
        output_base_dir (str): Base directory where the subdirectories will be created.

    Returns:
        str: The next available directory name.
    """
    # List all subdirectories in the base directory
    existing_dirs = [d for d in os.listdir(output_base_dir) if os.path.isdir(os.path.join(output_base_dir, d))]
    # Find the highest number and increment by 1
    next_dir_num = 1
    if existing_dirs:
        existing_dirs = [int(d) for d in existing_dirs if d.isdigit()]
        if existing_dirs:
            next_dir_num = max(existing_dirs) + 1
    
    return os.path.join(output_base_dir, str(next_dir_num))


def extract_frames_from_all_videos(input_folder, output_base_folder, fps=10):
    """
    Extract frames from all MP4 videos in a folder.

    Args:
        input_folder (str): Folder containing MP4 videos.
        output_base_folder (str): Base folder to save extracted frames.
        fps (int): Frames per second to extract.
    """
    # Create output base folder if it doesn't exist
    os.makedirs(output_base_folder, exist_ok=True)
    
    # Loop through all files in the input folder
    for video_file in os.listdir(input_folder):
        if video_file.endswith(".mp4"):
            video_path = os.path.join(input_folder, video_file)
            # Create a new output folder (incrementing directory number) for each video
            output_dir = get_next_directory(output_base_folder)
            # Extract frames from the current video
            extract_frames_from_video(video_path, output_dir, fps)

if __name__ == "__main__":
    # Get the current script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Define paths relative to exercise_dataset directory
    push_up_video_dir = os.path.join(script_dir, 'video_dataset', 'push_up_video')
    sit_up_video_dir = os.path.join(script_dir, 'video_dataset', 'sit_up_video')
    squat_video_dir = os.path.join(script_dir, 'video_dataset', 'squat_video')
    
    # Create image_dataset inside exercise_dataset directory
    image_dataset_dir = os.path.join(script_dir, 'image_dataset')
    push_up_output_dir = os.path.join(image_dataset_dir, 'push_up')
    sit_up_output_dir = os.path.join(image_dataset_dir, 'sit_up')
    squat_output_dir = os.path.join(image_dataset_dir, 'squat')
    
    # Ensure base directories exist
    os.makedirs(push_up_output_dir, exist_ok=True)
    os.makedirs(sit_up_output_dir, exist_ok=True)
    os.makedirs(squat_output_dir, exist_ok=True)
    
    # Process videos
    extract_frames_from_all_videos(push_up_video_dir, push_up_output_dir)
    print("push_up done")
    extract_frames_from_all_videos(sit_up_video_dir, sit_up_output_dir)
    print("sit_up done")
    extract_frames_from_all_videos(squat_video_dir, squat_output_dir)
    print("squat done")