const assert = require('assert');
const { test } = require('node:test');

const {
  createTrayStatusIcon,
  decodeTrayStatusIconRepresentation,
} = require('../electron/dist/main_runtime/trayStatusIcon.js');

function createNativeImageStub(options = {}) {
  const decodedByPath = options.decodedByPath ?? new Map();
  const target = {
    representations: [],
    template: null,
    addRepresentation(representation) {
      this.representations.push(representation);
    },
    setTemplateImage(value) {
      this.template = value;
    },
  };
  return {
    target,
    codec: {
      createEmpty: () => target,
      createFromPath: (iconPath) => {
        const decoded = decodedByPath.get(iconPath) ?? {
          buffer: Buffer.from(`decoded:${iconPath}`),
          empty: false,
          height: 16,
          width: 16,
        };
        return {
          getSize: () => ({ height: decoded.height, width: decoded.width }),
          isEmpty: () => Boolean(decoded.empty),
          toBitmap: () => decoded.buffer,
        };
      },
    },
  };
}

test('tray status icon decodes files before adding native image representations', () => {
  const decodedByPath = new Map([
    ['/icons/idle.png', { buffer: Buffer.from('raw-1x'), empty: false, height: 16, width: 16 }],
    ['/icons/idle@2x.png', { buffer: Buffer.from('raw-2x'), empty: false, height: 32, width: 32 }],
  ]);
  const { codec, target } = createNativeImageStub({ decodedByPath });

  const image = createTrayStatusIcon({
    iconPath: '/icons/idle.png',
    nativeImage: codec,
    retinaIconPath: '/icons/idle@2x.png',
    visual: 'idle',
  });

  assert.equal(image, target);
  assert.deepStrictEqual(target.representations, [
    { buffer: Buffer.from('raw-1x'), height: 16, scaleFactor: 1, width: 16 },
    { buffer: Buffer.from('raw-2x'), height: 32, scaleFactor: 2, width: 32 },
  ]);
  assert.equal(target.template, true);
});

test('tray status icon throws when an icon file cannot be decoded', () => {
  const decodedByPath = new Map([
    ['/icons/broken.png', { buffer: Buffer.alloc(0), empty: true, height: 0, width: 0 }],
  ]);
  const { codec } = createNativeImageStub({ decodedByPath });

  assert.throws(
    () =>
      decodeTrayStatusIconRepresentation({
        iconPath: '/icons/broken.png',
        nativeImage: codec,
      }),
    /could not be decoded/
  );
});
