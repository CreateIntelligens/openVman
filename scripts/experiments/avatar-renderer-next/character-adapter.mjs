/** Compatibility reader for existing character data. Data provenance is documented in PROVENANCE.md. */
export async function loadCharacter(base) {
  const bytes = async (name) => {
    const r = await fetch(`${base}/${name}`);
    if (!r.ok) throw new Error(`Character asset ${name}: ${r.status}`);
    return r.arrayBuffer();
  };
  const [vb, ib, morph, frames, teeth, weights] = await Promise.all([
    bytes("face_mesh_vbo_3700v.bin"),
    bytes("face_mesh_ibo_18672i.bin"),
    bytes("texture_bs_3700x6.bin"),
    bytes("json_data_151.json").then((data) =>
      JSON.parse(new TextDecoder().decode(data)),
    ),
    bytes("texture_teeth_180x180.bin"),
    bytes("weight_map_180x180.bin"),
  ]);
  const vertices = new Float32Array(vb),
    indices = new Uint32Array(ib);
  if (
    vertices.length % 11 ||
    !Array.isArray(frames) ||
    !frames.length ||
    frames.some(
      (f) => !Array.isArray(f) || f.length !== 950 || !f.every(Number.isFinite),
    )
  )
    throw new Error("Invalid character layout");
  const count = vertices.length / 11;
  if (
    new Uint8Array(morph).length !== count * 6 * 4 ||
    teeth.byteLength !== 576 * 192 * 4
  )
    throw new Error("Invalid atlas dimensions");
  if (
    !vertices.every(Number.isFinite) ||
    !indices.length ||
    indices.length % 3 ||
    indices.some((i) => i >= count) ||
    weights.byteLength !== 180 * 180 * 4
  )
    throw new Error("Invalid mesh or weight map");
  for (let i = 0; i < count; i++) {
    const reference = vertices[i * 11 + 6];
    if (!Number.isInteger(reference) || reference < 0 || reference >= count)
      throw new Error("Invalid morph reference");
  }
  return {
    vertices,
    indices,
    count,
    morph: new Uint8Array(morph),
    frames,
    teeth: new Uint8Array(teeth),
    weights: new Uint8Array(weights),
    size: 180,
  };
}

// CPU-side character binding leaves the graphics backend independent of the source asset layout.
export class CharacterBinding {
  constructor(asset) {
    this.asset = asset;
    this.buffer = new Float32Array(asset.count * 12);
  }
  update(frameIndex, coefficients) {
    if (!Number.isInteger(frameIndex) || frameIndex < 0)
      throw new Error("Invalid frame index");
    if (
      coefficients.length < 6 ||
      !Array.from(coefficients).every(Number.isFinite)
    )
      throw new Error("Invalid morph controls");
    const a = this.asset,
      f = a.frames[frameIndex % a.frames.length],
      m = f;
    const transform = (x, y, z, w = 1) => [
      m[0] * x + m[4] * y + m[8] * z + m[12] * w,
      m[1] * x + m[5] * y + m[9] * z + m[13] * w,
      m[2] * x + m[6] * y + m[10] * z + m[14] * w,
    ];
    for (let i = 0; i < a.count; i++) {
      const b = i * 11,
        kind = a.vertices[b + 5],
        reference = Math.round(a.vertices[b + 6]);
      let x = a.vertices[b],
        y = a.vertices[b + 1],
        z = a.vertices[b + 2];
      if (kind < 3) {
        for (let axis = 0; axis < 3; axis++) {
          let displacement = 0;
          for (let k = 0; k < 6; k++)
            displacement +=
              coefficients[k] *
              (a.morph[(k * a.count + reference) * 4 + axis] / 127.5 - 1);
          if (axis === 0) x += displacement;
          else if (axis === 1) y += displacement;
          else z += displacement;
        }
      } else if (kind === 4) {
        // Existing lower-jaw asset uses a rest translation plus its paired mouth controls.
        const jaw = coefficients[0] + coefficients[1];
        y += 7 + jaw / 3;
        z += Math.max(0, jaw / 3.9);
      }
      const position = transform(x, y, z),
        normal = transform(
          a.vertices[b + 8],
          a.vertices[b + 9],
          a.vertices[b + 10],
          0,
        );
      let flowX = 0,
        flowY = 0;
      if (kind !== -1 && reference < 465) {
        const offset =
          reference < 209 ? 16 + reference * 2 : 438 + (reference - 209) * 2;
        flowX = (position[0] - f[offset]) / a.size;
        flowY = (position[1] - f[offset + 1]) / a.size;
      }
      const material = kind >= 3 && kind < 6 ? 1 : 0;
      this.buffer.set(
        [
          ...position,
          ...normal,
          a.vertices[b + 3],
          a.vertices[b + 4],
          flowX,
          flowY,
          material,
          0,
        ],
        i * 12,
      );
    }
    return this.buffer;
  }
  region(frameIndex) {
    const f = this.asset.frames[frameIndex % this.asset.frames.length];
    return f.slice(434, 438);
  }
}
