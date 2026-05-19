module.exports = {
  appId: 'com.aicoding.desktop',
  productName: 'AI Coding Assistant',
  directories: {
    output: 'dist-electron',
    buildResources: 'build',
  },
  files: [
    'dist/**/*',
    'electron/**/*',
    'package.json',
  ],
  win: {
    target: ['nsis'],
    icon: 'build/icon.ico',
  },
  mac: {
    target: ['dmg'],
    icon: 'build/icon.icns',
    category: 'public.app-category.developer-tools',
  },
  linux: {
    target: ['AppImage'],
    icon: 'build/icon.png',
    category: 'Development',
  },
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    shortcutName: 'AI Coding Assistant',
  },
  extraResources: [],
}
