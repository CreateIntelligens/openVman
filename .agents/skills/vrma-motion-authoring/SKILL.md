---
name: vrma-motion-authoring
description: Author, inspect, validate, or integrate VRM Animation (.vrma) files for OpenVman. Use when the user asks to create VRMA motions, generate gestures for VRM avatars, convert BVH/FBX/pose data to VRMA, validate VRMC_vrm_animation files, or wire .vrma playback through three-vrm-animation/widget.html.
license: MIT
compatibility: OpenVman avatar widget; VRM 1.0/glTF 2.0; @pixiv/three-vrm-animation.
metadata:
  author: openVman
  version: "0.1"
---

# VRMA Motion Authoring

Use this skill for project work involving `.vrma` files: creating simple motions, converting motion sources, validating VRM Animation assets, or integrating gestures into the OpenVman VRM renderer.

## First Checks

Before changing code or assets, inspect the current runtime path:

```bash
rg -n "VRMAnimationLoaderPlugin|createVRMAnimationClip|GESTURES|gesture3D|vrma" frontend/app/public/vendor/ai-avatar-bot/widget.html frontend/app/src
```

For OpenVman, the important files are:

- `frontend/app/public/vendor/ai-avatar-bot/widget.html` - VRM renderer and `.vrma` playback path.
- `frontend/app/src/App.vue` - main avatar stage and iframe wiring.
- `frontend/app/src/data/mascotCatalog.ts` - VRM avatar catalog and widget URL builder.
- `frontend/app/src/__tests__/App.mascot-switcher.test.mjs` - static regression coverage for avatar renderer wiring.

Do not confuse:

- `.vrm`: humanoid avatar model.
- `.vrma`: animation data that can be retargeted to a VRM humanoid.
- `.glb` / `.gltf`: container formats. `.vrma` is a glTF 2.0 based animation asset with `VRMC_vrm_animation`.

## Core Facts

VRMA is not a video and not a model. Treat it as a humanoid motion asset:

- Use glTF core animation data for keyframes.
- Add root extension `VRMC_vrm_animation` with `specVersion: "1.0"`.
- Map animation nodes to VRM humanoid bones, expressions, and LookAt.
- Keep body bone scale out of animation.
- Animate translation only where allowed, normally hips for body motion.
- Use quaternion rotations for bone rotations.
- Keep expression weights in `[0, 1]`; clamp defensively.
- Use about 30 FPS as a practical authoring guideline unless the source motion requires more precision.

Primary references:

- VRM Animation spec: `https://github.com/vrm-c/vrm-specification/tree/master/specification/VRMC_vrm_animation-1.0`
- three-vrm-animation package: `https://github.com/pixiv/three-vrm/tree/dev/packages/three-vrm-animation`

## Choose The Work Mode

### Integrating existing `.vrma`

Use this path when the user already has motion files or URLs.

1. Confirm the file URL returns binary/glTF data, not HTML fallback.
2. Keep gesture URLs close to the existing `GESTURES` map in `widget.html`, unless a larger asset catalog is being introduced.
3. Register `VRMAnimationLoaderPlugin` on the same `GLTFLoader` used for VRM loading.
4. Load `.vrma` with `loader.loadAsync(file)`.
5. Read `gltf.userData.vrmAnimations[0]`.
6. Build a clip with `createVRMAnimationClip(animation, vrm)`.
7. Play through `THREE.AnimationMixer(vrm.scene)`.

For OpenVman's passive speaking mode, avoid gesture clips that fight mouth or gaze control. Prefer body-only clips for ambient gestures:

```js
const bodyOnly = (clip) => {
  clip.tracks = clip.tracks.filter((track) => /\.quaternion$/.test(track.name));
  return clip;
};
```

Use full clips only when the gesture intentionally controls expressions or LookAt and does not conflict with live TTS mouth movement.

### Authoring simple procedural `.vrma`

Use this path for simple gestures that can be described as keyframes:

- Idle breathing
- Small nod
- Slight head turn
- Thinking pose
- Wave
- Bow
- Look around
- Relaxed stance variation

Keep the motion short and restrained. Author a small set of keyframes with eased timing. Mirror left/right limb rotations intentionally. Avoid over-rotating shoulders, wrists, neck, or spine.

For gestures in OpenVman, prefer:

- 1-4 seconds duration.
- Loopable idle motions or one-shot greeting motions.
- Body-only motion if the avatar is speaking.
- No root teleporting.
- No scale animation.

### Converting motion sources

Use this path for BVH, FBX, mocap, or video-derived pose data.

Do not hand-wave retargeting. Identify the source skeleton and map it to VRM humanoid bones. Verify:

- Source rest pose versus VRM T-pose.
- Coordinate system and handedness.
- Unit scale.
- Hips/root translation behavior.
- Bone rotation order and conversion to quaternions.
- Missing fingers, eyes, jaw, or shoulders.

For complex full-body motion, prefer a proven converter or animation toolchain over hand-written JSON. AI-authored keyframes are acceptable for simple gestures; natural dance, walking, or acting requires motion source data or iterative visual review.

## OpenVman Integration Guardrails

OpenVman currently imports `@pixiv/three-vrm-animation` in `widget.html` and uses:

- `VRMAnimationLoaderPlugin`
- `createVRMAnimationClip`
- `THREE.AnimationMixer`
- `gestureActions`
- `gesture3D`

When changing playback behavior:

1. Keep the renderer transparent so the main stage background remains visible.
2. Do not break the parent page mouth-control protocol:
   - `postMessage({ ns: "avatar-widget-host", type: "mouth", volume })`
   - `postMessage({ ns: "avatar-widget-host", type: "mouth-stop" })`
3. Do not let ambient gestures override live mouth expression.
4. Keep external gesture URLs replaceable with local assets later.
5. Log failed gesture loads without failing the whole avatar renderer.

When adding UI for gesture choices, use the existing settings patterns in `SettingsModal.vue`; do not reintroduce a separate 2D/3D mode selector if the user-facing concept is MatesX versus VRM.

## Validation

For code integration changes, run targeted checks:

```bash
node --test frontend/app/src/__tests__/App.mascot-switcher.test.mjs frontend/app/src/components/controls/__tests__/SettingsModal.project-selector.test.mjs frontend/app/src/data/__tests__/mascotCatalog.test.mjs
pnpm --dir frontend/app exec vue-tsc --noEmit
pnpm --dir frontend/app exec vite build --outDir /tmp/openvman-vrma-dist --emptyOutDir true
```

For asset validation, verify at minimum:

- The `.vrma` URL does not return `<!DOCTYPE html>`.
- `GLTFLoader` can parse the file.
- `gltf.userData.vrmAnimations` has at least one animation.
- `createVRMAnimationClip(animation, vrm)` creates a non-empty clip.
- The clip does not contain unwanted mouth/expression/lookAt tracks when used as body-only gesture.
- The gesture finishes cleanly and returns control to the procedural idle pose.

## Output Expectations

When reporting results, include:

- Whether the work was asset authoring, conversion, validation, or runtime integration.
- Which `.vrma` files or URLs were used.
- Whether the motion is body-only or includes expression/lookAt tracks.
- What was verified locally.
- Any remaining visual-review risk, especially for full-body motion naturalness.
